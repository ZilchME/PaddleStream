# 流式ASR、TTS服务端

### 简介

对百度飞桨 [PaddleSpeech](https://github.com/PaddlePaddle/PaddleSpeech/) 服务进行二次封装，支持流式实时语音识别，支持文本逐字输入的流式语音合成。

### 前置服务

PaddleSpeech 支持通过服务配置文件作为服务端程序直接启动，本项目基于该服务端运行

```shell
paddlespeech_server start --config_file application.yaml
```

配置文件可以参考根目录的 `application.yaml`

可选开启ASR结果的标点补全服务，配置文件参考官方库提供的 demo 即可

```shell
paddlespeech_server start --config_file conf/punc_application.yaml
```

### 事件接口

TODO: 待补充