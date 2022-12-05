import sys
import json
import uuid
import requests
import pandas as pd
import streamlit as st
import snowflake.connector
from urllib.parse import quote_plus
from sqlalchemy import create_engine
from snowflake.connector.pandas_tools import pd_writer

user = st.secrets["snowflake"]["user"]
password = st.secrets["snowflake"]["password"]
account = st.secrets["snowflake"]["account"]
warehouse = st.secrets["snowflake"]["warehouse"]
database = st.secrets["snowflake"]["database"]
schema = st.secrets["snowflake"]["schema"]
table = st.secrets["others"]["table"]

API_HOST = st.secrets["datarobot"]["API_HOST"]
API_URL = "https://{api_host}/predApi/v1.0/deployments/{deployment_id}/predictionsUnstructured"  # noqa
API_KEY = st.secrets["datarobot"]["API_KEY"]
DATAROBOT_KEY = st.secrets["datarobot"]["DATAROBOT_KEY"]
DEPLOYMENT_ID = st.secrets["datarobot"]["DEPLOYMENT_ID"]

# Don't change this. It is enforced server-side too.
MAX_PREDICTION_FILE_SIZE_BYTES = 52428800  # 50 MB

columns = ["ID", "SUB_ID", "INPUT", "OUTPUT", "RATING"]
sf_url = "snowflake://{user}:{password}@{account}/{db}/{schema}?warehouse={warehouse}"
sql_update = """
UPDATE {database}.{schema}.{table} s
SET s.RATING = {rate}
WHERE s.ID='{id}'
AND s.SUB_ID ='{id_sub}';
"""


class DataRobotPredictionError(Exception):
    """Raised if there are issues getting predictions from DataRobot"""


def make_datarobot_deployment_unstructured_predictions(
    data, deployment_id, mimetype="text/plain", charset="UTF-8"
):
    """
    Make unstructured predictions on data provided using DataRobot deployment_id provided.
    See docs for details:
         https://app.datarobot.com/docs-jp/predictions/api/dr-predapi.html

    Parameters
    ----------
    data : bytes
        Bytes data read from provided file.
    deployment_id : str
        The ID of the deployment to make predictions with.
    mimetype : str
        Mimetype describing data being sent.
        If mimetype starts with 'text/' or equal to 'application/json',
        data will be decoded with provided or default(UTF-8) charset
        and passed into the 'score_unstructured' hook implemented in custom.py provided with the model.

        In case of other mimetype values data is treated as binary and passed without decoding.
    charset : str
        Charset should match the contents of the file, if file is text.

    Returns
    -------
    data : bytes
        Arbitrary data returned by unstructured model.


    Raises
    ------
    DataRobotPredictionError if there are issues getting predictions from DataRobot
    """
    # Set HTTP headers. The charset should match the contents of the file.
    headers = {
        "Content-Type": "{};charset={}".format(mimetype, charset),
        "Authorization": "Bearer {}".format(API_KEY),
        "DataRobot-Key": DATAROBOT_KEY,
    }

    url = API_URL.format(api_host=API_HOST, deployment_id=deployment_id)

    # Make API request for predictions
    predictions_response = requests.post(
        url,
        data=data.encode("UTF-8"),
        headers=headers,
    )
    _raise_dataroboterror_for_status(predictions_response)
    # Return raw response content
    return predictions_response.content


def _raise_dataroboterror_for_status(response):
    """Raise DataRobotPredictionError if the request fails along with the response returned"""
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError:
        err_msg = "{code} Error: {msg}".format(
            code=response.status_code, msg=response.text
        )
        raise DataRobotPredictionError(err_msg)


def predict(data, deployment_id=DEPLOYMENT_ID):
    data_size = sys.getsizeof(data)
    if data_size >= MAX_PREDICTION_FILE_SIZE_BYTES:
        print(
            (
                "Input file is too large: {} bytes. " "Max allowed size is: {} bytes."
            ).format(data_size, MAX_PREDICTION_FILE_SIZE_BYTES)
        )
        return None
    try:
        predictions = make_datarobot_deployment_unstructured_predictions(
            data, deployment_id
        )
    except DataRobotPredictionError as exc:
        print(exc)
        return None
    return predictions


@st.experimental_singleton
def init_connection():
    return snowflake.connector.connect(
        user=user,
        password=password,
        account=account,
        warehouse=warehouse,
        database=database,
        schema=schema,
        client_session_keep_alive=True,
    ), create_engine(
        sf_url.format(
            user=user,
            password=quote_plus(password),
            account=account,
            db=database,
            schema=schema,
            warehouse=warehouse,
        )
    )


def summerized_n_record():
    if input == "":
        st.session_state["status_msg"] = "文書を貼り付けてください"
        return None
    # reset
    st.session_state["id"] = uuid.uuid4().hex
    st.session_state["id_sub"] = uuid.uuid4().hex
    st.session_state["input"] = input.strip(" ").strip("\n")
    st.session_state["sent"] = False
    st.session_state["output"] = ""
    st.session_state["disable_dl"] = True
    # predict
    preds = predict(st.session_state["input"])
    preds = json.loads(preds)
    st.session_state["output"] = "\n".join(
        [summary["summary_text"] for summary in preds["prediction"]]
    )
    t = preds["model_run_time_seconds"]

    # record to sf
    df = pd.DataFrame(
        [
            (
                st.session_state["id"],
                st.session_state["id_sub"],
                st.session_state["input"],
                st.session_state["output"],
                0,
            )
        ],
        columns=columns,
    )
    df.to_sql(
        table, engine, if_exists="append", index=False, schema=schema, method=pd_writer
    )
    # change display
    # output_area.text_area(label="要約結果", value=output, disabled=st.session_state["disable_dl"])
    st.session_state["status_msg"] = f"計算時間: {t:.2f}秒"
    st.session_state["disable_dl"] = False


def update_status(id, id_sub, rate):
    with conn.cursor() as cur:
        _sql = sql_update.format(
            database=database,
            schema=schema,
            table=table,
            rate=rate,
            id=id,
            id_sub=id_sub,
        )
        print(_sql)
        cur.execute(_sql)


def upvote_callback():
    if st.session_state["sent"]:
        st.session_state["status_msg"] = "既に送信した"
    elif st.session_state["output"] == "":
        st.session_state["status_msg"] = "まだ要約してない"
    else:
        update_status(st.session_state["id"], st.session_state["id_sub"], 1)
        st.session_state["status_msg"] = "👍を記録した！"
        st.session_state["sent"] = True


def downvote_callback():
    if st.session_state["sent"]:
        st.session_state["status_msg"] = "既に送信した"
    elif st.session_state["output"] == "":
        st.session_state["status_msg"] = "まだ要約してない"
    else:
        update_status(st.session_state["id"], st.session_state["id_sub"], -1)
        st.session_state["status_msg"] = "👎を記録した..."
        st.session_state["sent"] = True


if "sent" not in st.session_state:
    st.session_state["sent"] = False
if "id" not in st.session_state:
    st.session_state["id"] = ""
if "id_sub" not in st.session_state:
    st.session_state["id_sub"] = ""
if "input" not in st.session_state:
    st.session_state["input"] = ""
if "output" not in st.session_state:
    st.session_state["output"] = ""
if "status_msg" not in st.session_state:
    st.session_state["status_msg"] = ""
if "disable_dl" not in st.session_state:
    st.session_state["disable_dl"] = True


conn, engine = init_connection()

header = st.header("日本語要約")
description = st.markdown(
    "Delivered by DataRobot, summerized based on [mt5](https://huggingface.co/tsmatz/mt5_summarize_japanese), made with :gift_heart:"
)
input = st.text_area(label="内容を入力")

_, col12, _ = st.columns([2, 1, 2])
with col12:
    button_summary = st.button("　要約　", on_click=summerized_n_record)

output_area = st.empty()
output_text = output_area.text_area(
    label="要約結果",
    value=st.session_state["output"],
    placeholder="「要約」をクリック",
    disabled=True,
)
_, col22, col23, _, col25 = st.columns([3, 1, 1, 1, 2])
send_status = st.empty()
if st.session_state["status_msg"]:
    send_status.info(st.session_state["status_msg"])
with col22:
    button_up = st.empty()
    button_up.button("👍", disabled=False, on_click=upvote_callback)
with col23:
    button_down = st.empty()
    button_down.button("👎", disabled=False, on_click=downvote_callback)
with col25:
    button_dl = st.empty()
    button_dl.download_button(
        "ダウンロード",
        st.session_state["output"],
        file_name="result.txt",
        disabled=st.session_state["disable_dl"],
    )
