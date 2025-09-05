from paddlespeech_client import ASROnlineClientExecutor

asrclient_executor = ASROnlineClientExecutor()
res = asrclient_executor(
    input="mic",
    # input="./zh.wav",
    server_ip="127.0.0.1",
    port=8090,
    # punc_server_ip="127.0.0.1",
    # punc_server_port=8190,
)
print(res)
