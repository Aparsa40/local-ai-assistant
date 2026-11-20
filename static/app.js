function chatApp() {
    return {
        sessions: [],
        currentSessionId: null,
        messages: [],
        inputMessage: '',
        isLoading: false,
        streamingSessionId: null,
        showSettings: false,
        activeTab: 'persona',
        sidebarCollapsed: localStorage.getItem('wiz-sidebar-collapsed') === 'true',
        sidebarWidth: Math.min(480, Math.max(240, Number(localStorage.getItem('wiz-sidebar-width')) || 288)),
        sidebarResizeStart: null,
        sidebarResizing: false,
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
        providerCapabilities: null,
        settings: {
            assistant_name: 'دستیار هوشمند',
            system_prompt: '',
            active_provider: 'openrouter',
            routing_mode: 'manual',
            providers_config: {
                ollama: { base_url: 'http://localhost:11434', model: '' },
                openrouter: { base_url: 'https://openrouter.ai/api/v1', model: 'openrouter/free', api_key: '' },
                google_ai_studio: { base_url: 'https://generativelanguage.googleapis.com/v1beta', model: 'gemini-3.8-flash', api_key: '' },
                cloudflare_workers_ai: { base_url: 'https://api.cloudflare.com/client/v4', account_id: '', model: '@cf/zai-org/glm-4.7-flash', api_key: '' },
                groq: { base_url: 'https://api.groq.com/openai/v1', model: 'openai/gpt-oss-20b', api_key: '' },
                cohere: { base_url: 'https://api.cohere.com', model: 'command-r7b-12-2024', api_key: '' }
            }
        },

        async init() {
            this.applyTheme();
            await this.loadProfile();
            await this.loadSettings();
            await this.loadProviders();
            await this.loadProviderCapabilities();
            await this.refreshModels();
            await this.loadSessions();
            // Keep previous conversations in the sidebar, but never reopen one automatically.
            await this.createNewSession();
        },

        async loadSettings() {
            const response = await fetch('/api/settings');
            if (!response.ok) throw new Error('بارگذاری تنظیمات ناموفق بود.');
            this.settings = await response.json();
            this.settings.providers_config ||= {};
            this.settings.providers_config.ollama ||= { base_url: 'http://localhost:11434', model: '' };
            this.settings.providers_config.openrouter ||= { base_url: 'https://openrouter.ai/api/v1', model: 'openrouter/free', api_key: '' };
            this.settings.providers_config.google_ai_studio ||= { base_url: 'https://generativelanguage.googleapis.com/v1beta', model: 'gemini-3.8-flash', api_key: '' };
            this.settings.providers_config.cloudflare_workers_ai ||= { base_url: 'https://api.cloudflare.com/client/v4', account_id: '', model: '@cf/zai-org/glm-4.7-flash', api_key: '' };
            this.settings.providers_config.groq ||= { base_url: 'https://api.groq.com/openai/v1', model: 'openai/gpt-oss-20b', api_key: '' };
            this.settings.providers_config.cohere ||= { base_url: 'https://api.cohere.com', model: 'command-r7b-12-2024', api_key: '' };
            this.updateProviderKeyHints();
        },

        updateProviderKeyHints() {
            const providers = [
                ['openrouter', 'https://openrouter.ai'],
                ['google_ai_studio', 'https://aistudio.google.com'],
                ['cloudflare_workers_ai', 'https://dash.cloudflare.com/'],
                ['groq', 'https://console.groq.com/keys'],
                ['cohere', 'https://dashboard.cohere.com/api-keys']
            ];
            for (const [id, url] of providers) {
                const config = this.settings.providers_config[id] || {};
                const input = document.querySelector(`input[x-model="settings.providers_config.${id}.api_key"]`);
                const hint = document.querySelector(`[data-key-hint="${id}"]`);
                if (input) input.placeholder = config.api_key_configured ? 'کلید ذخیره شده است' : 'کلید API را وارد کنید';
                if (hint && config.api_key_configured) hint.textContent = `کلید قبلی ذخیره شده است؛ برای حفظ آن فیلد را خالی بگذارید. ${url}`;
            }
        },

        async loadProviders() {
            const response = await fetch('/api/providers');
            if (response.ok) this.availableProviders = await response.json();
        },

        async onProviderChange() {
            await this.loadProviderCapabilities();
            await this.refreshModels();
        },

        async loadProviderCapabilities() {
            this.providerCapabilities = null;
            const provider = this.settings.active_provider;
            if (!['cloudflare_workers_ai', 'groq', 'cohere'].includes(provider)) return;
            try {
                const response = await fetch(`/api/providers/${encodeURIComponent(provider)}/capabilities`);
                if (!response.ok) return;
                this.providerCapabilities = await response.json();
            } catch (error) {
                console.warn('Provider capability discovery failed:', error);
            }
        },

        async refreshModels() {
            this.modelsLoading = true;
            this.modelsError = '';
            const provider = this.settings.active_provider;
            const config = this.settings.providers_config[provider] ||= {};
            const defaultModel = config.model || '';

            // Do not make a network request until the provider credentials are present.
            const credentialsReady = provider === 'cloudflare_workers_ai'
                ? Boolean(config.api_key && config.account_id)
                : ['groq', 'cohere'].includes(provider)
                    ? Boolean(config.api_key)
                    : true;

            if (!credentialsReady) {
                this.availableModels = defaultModel ? [defaultModel] : [];
                this.modelsError = 'برای دریافت فهرست زنده مدل‌ها، ابتدا اطلاعات اتصال این Provider را وارد کنید.';
                this.modelsLoading = false;
                return;
            }

            this.availableModels = defaultModel ? [defaultModel] : [];
            try {
                const response = await fetch(`/api/providers/${encodeURIComponent(provider)}/models`);
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'دریافت فهرست مدل‌ها ناموفق بود.');
                const discoveredModels = data.models || [];
                this.availableModels = discoveredModels;
                // Keep the configured default if discovery returns an empty or partial catalog.
                if (discoveredModels.length && !discoveredModels.includes(config.model)) {
                    config.model = discoveredModels[0];
                }
            } catch (error) {
                this.modelsError = error.message;
                // Discovery is optional; never erase a working default because an API is unavailable.
                this.availableModels = defaultModel ? [defaultModel] : [];
                if (provider === 'openrouter') {
                    this.availableModels = ['openrouter/free'];
                    config.model ||= 'openrouter/free';
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
            this.updateProviderKeyHints();
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
            if (this.showSettings) {
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

        async deleteSession(session) {
            if (!session || this.streamingSessionId === session.id) return;
            const confirmed = confirm(`نشست «${session.title}» و تمام پیام‌های آن برای همیشه حذف شود؟`);
            if (!confirmed) return;

            try {
                const response = await fetch(`/api/sessions/${session.id}`, { method: 'DELETE' });
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'حذف نشست ناموفق بود.');

                this.sessions = this.sessions.filter(item => item.id !== session.id);
                this.openSessionMenuId = null;
                if (this.editingSessionId === session.id) this.cancelSessionRename();

                if (this.currentSessionId === session.id) {
                    this.currentSessionId = null;
                    this.messages = [];
                    if (this.sessions.length > 0) {
                        await this.selectSession(this.sessions[0].id);
                    } else {
                        await this.createNewSession();
                    }
                }
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

        handleMessageKeydown(event) {
            // Do not submit while an IME (including Persian input) is composing text.
            if (event.isComposing || event.keyCode === 229) return;

            // Shift+Enter (and Alt+Enter) keep the native textarea newline behavior.
            if ((event.shiftKey || event.altKey) && !event.ctrlKey && !event.metaKey) return;

            // Enter and Ctrl/Cmd+Enter submit the message instead of inserting a newline.
            event.preventDefault();
            if (!this.isLoading && this.inputMessage.trim()) {
                this.sendMessage();
            }
        },

        async sendMessage() {
            if (!this.inputMessage.trim() || this.isLoading) return;
            const userText = this.inputMessage;
            this.inputMessage = '';
            this.isLoading = true;
            this.streamingSessionId = this.currentSessionId;
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
                // This endpoint serves local metadata only; it does not call provider model catalogs.
                await this.loadProviderCapabilities();
            } catch (error) {
                this.messages[aiMsgIndex].content = `خطا در ارتباط با سرور: ${error.message}`;
            } finally {
                this.isLoading = false;
                this.streamingSessionId = null;
            }
        }
    };
}
