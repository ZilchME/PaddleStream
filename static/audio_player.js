class PCMAudioPlayer {
    constructor(sampleRate) {
        this.sampleRate = sampleRate; // 音频采样率
        this.audioContext = null; // Web Audio上下文
        this.audioQueue = []; // 音频数据队列
        this.isPlaying = false; // 是否正在播放
        this.currentSource = null; // 当前音频源
        this.bufferThreshold = 0.5; // 缓冲阈值(秒)，达到后才开始播放
        this.bytesPerSecond = sampleRate * 2; // 每秒字节数(16位=2字节/样本)
        this.lastPlaybackTime = 0; // 上次播放结束时间
        this.playbackRate = 1.0; // 播放速率(1.0=正常速度)
        this.gainNode = null; // 音量控制节点
        this.volume = 1.0; // 音量(0.0-1.0)
        
        // 播放状态监听器
        this.onPlaybackStart = null;
        this.onPlaybackEnd = null;
        this.onBufferUpdate = null;
    }

    // 连接音频上下文
    async connect() {
        if (!this.audioContext) {
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
                sampleRate: this.sampleRate // 确保使用指定采样率
            });
            
            // 创建音量控制节点
            this.gainNode = this.audioContext.createGain();
            this.gainNode.connect(this.audioContext.destination);
            this.gainNode.gain.value = this.volume;
        }
        
        // 如果上下文被暂停，恢复它
        if (this.audioContext.state === 'suspended') {
            await this.audioContext.resume();
        }
    }

    // 推送PCM数据到队列
    pushPCM(arrayBuffer) {
        this.audioQueue.push(arrayBuffer);
        this._playNextAudio();
        
        // 触发缓冲区更新回调
        if (this.onBufferUpdate) {
            this.onBufferUpdate(this.audioQueue.length, this._getBufferedTime());
        }
    }

    // 获取当前缓冲时间
    _getBufferedTime() {
        const totalSamples = this.audioQueue.reduce((acc, buffer) => acc + (buffer.byteLength / 2), 0);
        return totalSamples / this.sampleRate;
    }

    // 将PCM数据转换为AudioBuffer
    _bufferPCMData(pcmData) {
        const length = pcmData.byteLength / 2; // 16位PCM，所以除以2
        const audioBuffer = this.audioContext.createBuffer(1, length, this.sampleRate);
        const channelData = audioBuffer.getChannelData(0);
        const int16Array = new Int16Array(pcmData);

        for (let i = 0; i < length; i++) {
            channelData[i] = int16Array[i] / 32768; // 16位转浮点(-1.0到1.0)
        }

        console.log(`准备音频: ${length}个样本, ${(length / this.sampleRate * 1000).toFixed(1)}毫秒`);
        return audioBuffer;
    }

    // 播放音频
    async _playAudio(arrayBuffer) {
        if (this.audioContext.state === 'suspended') {
            await this.audioContext.resume();
        }

        const audioBuffer = this._bufferPCMData(arrayBuffer);
        this.currentSource = this.audioContext.createBufferSource();
        this.currentSource.buffer = audioBuffer;
        this.currentSource.playbackRate.value = this.playbackRate;
        
        // 连接到音量控制节点
        this.currentSource.connect(this.gainNode);

        const now = this.audioContext.currentTime;
        const bufferDuration = audioBuffer.duration / this.playbackRate;

        // 计算开始时间，确保与前一段音频连续
        const startTime = Math.max(now, this.lastPlaybackTime);
        this.currentSource.start(startTime);
        this.lastPlaybackTime = startTime + bufferDuration;

        this.currentSource.onended = () => {
            console.log('音频播放结束');
            this.isPlaying = false;
            this.currentSource = null;
            
            // 触发播放结束回调
            if (this.onPlaybackEnd) {
                this.onPlaybackEnd();
            }
            
            this._playNextAudio(); // 播放队列中的下一段音频
        };

        if (!this.isPlaying) {
            this.isPlaying = true;
            // 触发播放开始回调
            if (this.onPlaybackStart) {
                this.onPlaybackStart();
            }
        }
    }

    // 播放下一段音频
    _playNextAudio() {
        // 计算当前队列中的总音频时长
        const bufferedTime = this._getBufferedTime();

        // 当缓冲达到阈值且没有正在播放的音频时
        if (bufferedTime >= this.bufferThreshold && !this.isPlaying && this.audioQueue.length > 0) {
            // 获取第一个音频块进行播放，保持队列中其他数据用于连续播放
            const audioBuffer = this.audioQueue.shift();
            this._playAudio(audioBuffer);
        }
    }

    // 停止播放
    stop() {
        if (this.currentSource) {
            this.currentSource.stop();
            this.currentSource = null;
            this.isPlaying = false;
        }
        this.audioQueue = [];
        this.lastPlaybackTime = 0;
        console.log('播放已停止，队列已清空');
        
        // 触发播放结束回调
        if (this.onPlaybackEnd) {
            this.onPlaybackEnd();
        }
    }

    // 暂停播放
    pause() {
        if (this.currentSource) {
            this.currentSource.stop();
            this.currentSource = null;
            this.isPlaying = false;
        }
        console.log('播放已暂停');
    }

    // 恢复播放
    resume() {
        if (!this.isPlaying && this.audioQueue.length > 0) {
            this._playNextAudio();
        }
    }

    // 设置播放速率(0.5-2.0)
    setPlaybackRate(rate) {
        this.playbackRate = Math.max(0.5, Math.min(2.0, rate)); // 限制在0.5-2.0倍速之间
        if (this.currentSource) {
            this.currentSource.playbackRate.value = this.playbackRate;
        }
        console.log(`播放速率设置为: ${this.playbackRate}x`);
    }

    // 设置缓冲阈值(秒)
    setBufferThreshold(seconds) {
        this.bufferThreshold = Math.max(0.1, Math.min(2.0, seconds)); // 限制在0.1-2.0秒之间
        console.log(`缓冲阈值设置为: ${this.bufferThreshold}秒`);
    }

    // 设置音量(0.0-1.0)
    setVolume(volume) {
        this.volume = Math.max(0.0, Math.min(1.0, volume));
        if (this.gainNode) {
            this.gainNode.gain.value = this.volume;
        }
        console.log(`音量设置为: ${(this.volume * 100).toFixed(0)}%`);
    }

    // 获取播放状态信息
    getStatus() {
        return {
            isPlaying: this.isPlaying,
            queueLength: this.audioQueue.length,
            bufferedTime: this._getBufferedTime(),
            sampleRate: this.sampleRate,
            playbackRate: this.playbackRate,
            volume: this.volume,
            bufferThreshold: this.bufferThreshold
        };
    }

    // 清空队列但不停止当前播放
    clearQueue() {
        this.audioQueue = [];
        console.log('音频队列已清空');
    }

    // 设置回调函数
    setCallbacks(callbacks) {
        if (callbacks.onPlaybackStart) {
            this.onPlaybackStart = callbacks.onPlaybackStart;
        }
        if (callbacks.onPlaybackEnd) {
            this.onPlaybackEnd = callbacks.onPlaybackEnd;
        }
        if (callbacks.onBufferUpdate) {
            this.onBufferUpdate = callbacks.onBufferUpdate;
        }
    }
}

// 支持多种模块系统
if (typeof module !== 'undefined' && module.exports) {
    // CommonJS
    module.exports = PCMAudioPlayer;
} else if (typeof define === 'function' && define.amd) {
    // AMD
    define([], function() {
        return PCMAudioPlayer;
    });
} else {
    // ES6 modules 和全局变量
    if (typeof window !== 'undefined') {
        window.PCMAudioPlayer = PCMAudioPlayer;
    }
}

export default PCMAudioPlayer;