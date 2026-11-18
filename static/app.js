function chatApp() {
    return {
        sessions: [],
        currentSessionId: null,
        messages: [],
        inputMessage: '',
        isLoading: false,
        showSettings: false,
        activeTab: 'persona',
        sidebarCollapsed: localStorage.getItem('wiz-sidebar-collapsed') === 'true',
        theme: localStorage.getItem('wiz-theme') || 'dark',
        profile: { display_name: 'کاربر', username: 'user', email: '', avatar_url: '' },
        profileDraft: { display_name: '', username: '', email: '' },
        profileSaving: false,
        openSessionMenuId: null,
        editingSessionId: null,
        editingSessionTitle: '',
        availableProviders: [],
        availableModels: [],
        modelsLoading: false,
        modelsError: '',
        settings: {
            assistant_name: 'دستیار هوشمند',
            system_prompt: '',
            active_provider: 'ollama',
            routing_mode: 'manual',
            providers_config: {
                ollama: { base_url: 'http://localhost:11434', model: '' },
                openrouter: { base_url: 'https://openrouter.ai/api/v1', model: 'openrouter/free', api_key: '' }
            }
        },

        async init() {
            this.applyTheme();
            await this.loadProfile();
            await this.loadSettings();
            await this.loadProviders();
            await this.refreshModels();
            await this.loadSessions();
            if (this.sessions.length === 0) await this.createNewSession();
            else await this.selectSession(this.sessions[0].id);
        },

        async loadSettings() {
            const response = await fetch('/api/settings');
            if (!response.ok) throw new Error('بارگذاری تنظیمات ناموفق بود.');
            this.settings = await response.json();
            this.settings.providers_config ||= {};
            this.settings.providers_config.ollama ||= { base_url: 'http://localhost:11434', model: '' };
            this.settings.providers_config.openrouter ||= { base_url: 'https://openrouter.ai/api/v1', model: 'openrouter/free', api_key: '' };
        },

        async loadProviders() {
            const response = await fetch('/api/providers');
            if (response.ok) this.availableProviders = await response.json();
        },

        async onProviderChange() {
            await this.refreshModels();
        },

        async refreshModels() {
            this.modelsLoading = true;
            this.modelsError = '';
            this.availableModels = [];
            const provider = this.settings.active_provider;
            try {
                const response = await fetch(`/api/providers/${encodeURIComponent(provider)}/models`);
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'دریافت فهرست مدل‌ها ناموفق بود.');
                this.availableModels = data.models || [];
                const config = this.settings.providers_config[provider] ||= {};
                if (!this.availableModels.includes(config.model)) {
                    config.model = this.availableModels[0] || '';
                }
            } catch (error) {
                this.modelsError = error.message;
                if (provider === 'openrouter') {
                    this.availableModels = ['openrouter/free'];
                    this.settings.providers_config.openrouter.model = 'openrouter/free';
                }
            } finally {
                this.modelsLoading = false;
            }
        },

        async saveSettings() {
            const response = await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.settings)
            });
            const data = await response.json();
            if (!response.ok) {
                alert(data.detail || 'ذخیره تنظیمات ناموفق بود.');
                return;
            }
            this.settings = data.config;
            this.showSettings = false;
            await this.refreshModels();
        },

        async loadProfile() {
            try {
                const response = await fetch('/api/profile');
                if (!response.ok) throw new Error('بارگذاری پروفایل ناموفق بود.');
                this.profile = await response.json();
                this.profileDraft = {
                    display_name: this.profile.display_name,
                    username: this.profile.username,
                    email: this.profile.email
                };
            } catch (error) {
                console.error(error);
            }
        },

        openAppSettings(tab = 'profile') {
            this.activeTab = tab;
            this.showSettings = true;
        },

        toggleAppSettings(tab = 'profile') {
            if (this.showSettings && this.activeTab === tab) {
                this.showSettings = false;
                return;
            }
            this.openAppSettings(tab);
        },

        toggleSidebar() {
            this.sidebarCollapsed = !this.sidebarCollapsed;
            localStorage.setItem('wiz-sidebar-collapsed', String(this.sidebarCollapsed));
        },

        applyTheme() {
            document.body.classList.toggle('theme-light', this.theme === 'light');
            localStorage.setItem('wiz-theme', this.theme);
        },

        setTheme(theme) {
            this.theme = theme;
            this.applyTheme();
        },

        cancelProfileEdit() {
            this.profileDraft = {
                display_name: this.profile.display_name,
                username: this.profile.username,
                email: this.profile.email
            };
        },

        async saveProfile() {
            this.profileSaving = true;
            try {
                const response = await fetch('/api/profile', {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.profileDraft)
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'ذخیره پروفایل ناموفق بود.');
                this.profile = { ...this.profile, ...data };
                this.cancelProfileEdit();
            } catch (error) {
                alert(error.message);
            } finally {
                this.profileSaving = false;
            }
        },

        async uploadAvatar(event) {
            const file = event.target.files?.[0];
            if (!file) return;
            event.target.value = '';
            if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
                alert('فقط فایل PNG، JPG یا WebP مجاز است.');
                return;
            }
            if (file.size > 2 * 1024 * 1024) {
                alert('حجم تصویر نباید بیشتر از ۲ مگابایت باشد.');
                return;
            }
            try {
                const response = await fetch('/api/profile/avatar', {
                    method: 'PUT',
                    headers: { 'Content-Type': file.type },
                    body: file
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'بارگذاری تصویر ناموفق بود.');
                this.profile = { ...this.profile, ...data, avatar_url: data.avatar_url + '?v=' + Date.now() };
            } catch (error) {
                alert(error.message);
            }
        },

        async removeAvatar() {
            if (!confirm('تصویر پروفایل حذف شود؟')) return;
            const response = await fetch('/api/profile/avatar', { method: 'DELETE' });
            const data = await response.json();
            if (!response.ok) {
                alert(data.detail || 'حذف تصویر ناموفق بود.');
                return;
            }
            this.profile = { ...this.profile, ...data };
        },

        async loadSessions() {
            const response = await fetch('/api/sessions');
            this.sessions = await response.json();
        },

        async createNewSession() {
            const response = await fetch('/api/sessions', { method: 'POST' });
            const newSession = await response.json();
            this.sessions.unshift(newSession);
            await this.selectSession(newSession.id);
        },

        async selectSession(id) {
            if (this.editingSessionId !== null) this.cancelSessionRename();
            this.openSessionMenuId = null;
            this.currentSessionId = id;
            const response = await fetch(`/api/sessions/${id}/messages`);
            this.messages = await response.json();
            this.scrollToBottom();
        },

        toggleSessionMenu(id) {
            this.openSessionMenuId = this.openSessionMenuId === id ? null : id;
        },

        startSessionRename(session) {
            this.editingSessionId = session.id;
            this.editingSessionTitle = session.title;
            this.openSessionMenuId = null;
        },

        cancelSessionRename() {
            this.editingSessionId = null;
            this.editingSessionTitle = '';
        },

        async saveSessionRename() {
            if (this.editingSessionId === null) return;
            const title = this.editingSessionTitle.trim();
            if (!title) {
                alert('عنوان نشست نمی‌تواند خالی باشد.');
                return;
            }

            const sessionId = this.editingSessionId;
            try {
                const response = await fetch(`/api/sessions/${sessionId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title })
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'تغییر نام نشست ناموفق بود.');

                const session = this.sessions.find(item => item.id === sessionId);
                if (session) session.title = data.title;
                this.cancelSessionRename();
            } catch (error) {
                alert(error.message);
            }
        },

        renderMarkdown(text) {
            // Escape raw HTML before Markdown parsing to avoid rendering model/user HTML.
            const safeText = (text || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            return marked.parse(safeText);
        },

        scrollToBottom() {
            setTimeout(() => {
                const container = document.getElementById('chat-container');
                if (container) container.scrollTop = container.scrollHeight;
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
                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'درخواست چت ناموفق بود.');
                }
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const events = buffer.split('\n\n');
                    buffer = events.pop() || '';
                    for (const event of events) {
                        const line = event.split('\n').find(part => part.startsWith('data:'));
                        if (!line) continue;
                        const data = JSON.parse(line.slice(5).trim());
                        if (data.type === 'meta') this.messages[aiMsgIndex].model = data.model;
                        else if (data.type === 'chunk') {
                            this.messages[aiMsgIndex].content += data.content;
                            this.scrollToBottom();
                        } else if (data.type === 'error') {
                            this.messages[aiMsgIndex].content += `\n\n❌ خطا: ${data.content}`;
                        }
                    }
                }
                if (buffer.trim().startsWith('data:')) {
                    const data = JSON.parse(buffer.trim().slice(5).trim());
                    if (data.type === 'error') this.messages[aiMsgIndex].content += `\n\n❌ خطا: ${data.content}`;
                }
                await this.loadSessions();
            } catch (error) {
                this.messages[aiMsgIndex].content = `خطا در ارتباط با سرور: ${error.message}`;
            } finally {
                this.isLoading = false;
            }
        }
    };
}
