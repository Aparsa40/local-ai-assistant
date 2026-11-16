function chatApp() {
    return {
        sessions: [],
        currentSessionId: null,
        messages: [],
        inputMessage: '',
        isLoading: false,
        showSettings: false,
        activeTab: 'persona',
        settings: {
            assistant_name: 'دستیار هوشمند',
            system_prompt: '',
            active_provider: 'ollama',
            routing_mode: 'auto',
            providers_config: { openrouter: { api_key: '' } }
        },

        async init() {
            await this.loadSettings();
            await this.loadSessions();
            if (this.sessions.length === 0) {
                await this.createNewSession();
            } else {
                await this.selectSession(this.sessions[0].id);
            }
        },

        async loadSettings() {
            const res = await fetch('/api/settings');
            this.settings = await res.json();
        },

        async saveSettings() {
            await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.settings)
            });
            this.showSettings = false;
        },

        async loadSessions() {
            const res = await fetch('/api/sessions');
            this.sessions = await res.json();
        },

        async createNewSession() {
            const res = await fetch('/api/sessions', { method: 'POST' });
            const newSession = await res.json();
            this.sessions.unshift(newSession);
            await this.selectSession(newSession.id);
        },

        async selectSession(id) {
            this.currentSessionId = id;
            const res = await fetch(`/api/sessions/${id}/messages`);
            this.messages = await res.json();
            this.scrollToBottom();
        },

        renderMarkdown(text) {
            return marked.parse(text || '');
        },

        scrollToBottom() {
            setTimeout(() => {
                const container = document.getElementById('chat-container');
                container.scrollTop = container.scrollHeight;
            }, 50);
        },

        async sendMessage() {
            if (!this.inputMessage.trim() || this.isLoading) return;

            const userText = this.inputMessage;
            this.inputMessage = '';
            this.isLoading = true;

            this.messages.push({ role: 'user', content: userText });
            const aiMsgIndex = this.messages.push({ role: 'assistant', content: '', model: 'در حال انتخاب مدل...' }) - 1;
            this.scrollToBottom();

            try {
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ session_id: this.currentSessionId, message: userText })
                });

                const reader = response.body.getReader();
                const decoder = new TextDecoder();

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    const chunkStr = decoder.decode(value);
                    const lines = chunkStr.split('\n\n');

                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            const data = JSON.parse(line.slice(6));
                            if (data.type === 'meta') {
                                this.messages[aiMsgIndex].model = data.model;
                            } else if (data.type === 'chunk') {
                                this.messages[aiMsgIndex].content += data.content;
                                this.scrollToBottom();
                            } else if (data.type === 'error') {
                                this.messages[aiMsgIndex].content += `\n\n❌ خطا: ${data.content}`;
                            }
                        }
                    }
                }
                await this.loadSessions(); // به‌روزرسانی عنوان چت در سایدبار
            } catch (err) {
                this.messages[aiMsgIndex].content = `خطا در ارتباط با سرور: ${err.message}`;
            } finally {
                this.isLoading = false;
            }
        }
    }
}