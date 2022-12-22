graph_string = """
digraph G {
    graph [charset = "UTF-8";
    rankdir = "TB"];
    node [fontname = "Handlee"];
    edge [fontname = "Handlee"];
    
    
    input [ label = "テキスト入力" ];
    
    summerization [ label = "要約" ];
    translation [ label = "英日翻訳" ];
    write [ label = "結果記録" ];
    judge [ label = "ユーザ判断";shape = diamond;];
    good [ label = "👍" ];
    bad [ label = "👎" ];
    datarobot [fillcolor="grey"];
    snowflake;
    
    input -> summerization;
    summerization -> translation;
    summerization:s -> datarobot;
    datarobot -> summerization;
    translation:s -> datarobot;
    datarobot -> translation
    translation -> write;
    write -> snowflake;
    write -> judge;
    
    judge -> good [ label = "いい" ];
    judge:e -> bad [ label = "悪い" ];
    good -> snowflake;
    bad -> snowflake;
}
"""
