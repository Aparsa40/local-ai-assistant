function chatApp() {
    return {
        sessions: [],
        currentSessionId: null,
        messages: [],
        inputMessage: '',
        isLoading: false,
        streamingSessionId: null,
        activeRequestId: null,
        pendingRetry: null,
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
        connectionLoading: false,
        connectionResult: null,
        providerCapabilities: null,
        providerQuota: null,
        catalogSyncLoading: false,
        catalogSyncResult: null,
        providerCatalogSnapshot: null,
        operationalReport: null,
        operationalReportLoading: false,
        intelligenceReport: null,
        intelligenceReportLoading: false,
        intelligenceReportError: '',
        agents: [],
        agentRuns: [],
        agentsLoading: false,
        agentsError: '',
        agentTaskForm: { title: '', query: '', scope_type: 'user', scope_id: '' },
        orchestrationPlans: [],
        orchestrationPlanDetail: null,
        orchestrationError: '',
        orchestrationLoading: false,
        orchestrationGoalForm: { description: '', success_criteria: '', scope_id: 'local-user' },
        settings: {
            assistant_name: 'دستیار هوشمند',
            system_prompt: '',
            active_provider: 'openrouter',
            routing_mode: 'manual',
            providers_config: {
                ollama: { base_url: 'http://localhost:11434', model: '', auto_start: true },
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
            await this.loadOperationalReport();
            await this.loadProviderCapabilities();
            await this.loadLatestIntelligenceReport();
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
            this.settings.providers_config.ollama ||= { base_url: 'http://localhost:11434', model: '', auto_start: true };
            this.settings.providers_config.ollama.auto_start ??= true;
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

        async loadOperationalReport() {
            this.operationalReportLoading = true;
            try {
                const response = await fetch('/api/operational-report');
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'بارگذاری گزارش عملیاتی ناموفق بود.');
                this.operationalReport = data;
            } catch (error) {
                console.warn('Operational report unavailable:', error);
            } finally {
                this.operationalReportLoading = false;
            }
        },

        async loadLatestIntelligenceReport() {
            this.intelligenceReportError = '';
            const provider = this.settings.active_provider;
            try {
                const response = await fetch('/api/intelligence/reports/latest?provider_id=' + encodeURIComponent(provider));
                const data = await response.json();
                if (response.status === 404) {
                    this.intelligenceReport = null;
                    return;
                }
                if (!response.ok) throw new Error(data.detail || 'بارگذاری گزارش هوشمند ناموفق بود.');
                this.intelligenceReport = data;
            } catch (error) {
                this.intelligenceReportError = error.message;
            }
        },

        async loadAgents() {
            this.agentsLoading = true;
            this.agentsError = '';
            try {
                const response = await fetch('/api/agents');
                if (!response.ok) throw new Error('HTTP ' + response.status);
                const data = await response.json();
                this.agents = data.agents || [];
            } catch (error) {
                this.agentsError = 'بارگذاری عامل‌ها ناموفق بود: ' + error.message;
            } finally {
                this.agentsLoading = false;
            }
        },

        async loadAgentRuns() {
            this.agentsLoading = true;
            this.agentsError = '';
            try {
                const response = await fetch('/api/agents/runs');
                if (!response.ok) throw new Error('HTTP ' + response.status);
                const data = await response.json();
                this.agentRuns = data.runs || [];
            } catch (error) {
                this.agentsError = 'بارگذاری اجراها ناموفق بود: ' + error.message;
            } finally {
                this.agentsLoading = false;
            }
        },

        async createAgentTask(agent) {
            this.agentsError = '';
            try {
                const response = await fetch('/api/agents/tasks', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        agent_id: agent.agent_id,
                        agent_version: agent.version,
                        title: this.agentTaskForm.title || ('تحلیل دانش ' + agent.agent_id),
                        query: this.agentTaskForm.query,
                        scope_type: this.agentTaskForm.scope_type,
                        scope_id: this.agentTaskForm.scope_id || 'local-user',
                    })
                });
                if (!response.ok) {
                    const detail = await response.json().catch(() => ({}));
                    throw new Error(detail.detail || ('HTTP ' + response.status));
                }
                await this.loadAgentRuns();
            } catch (error) {
                this.agentsError = 'ایجاد وظیفه ناموفق بود: ' + error.message;
            }
        },

        async executeAgentRun(runId) {
            this.agentsError = '';
            try {
                const response = await fetch('/api/agents/runs/' + encodeURIComponent(runId) + '/execute', { method: 'POST' });
                if (!response.ok) {
                    const detail = await response.json().catch(() => ({}));
                    throw new Error(detail.detail || ('HTTP ' + response.status));
                }
                await this.loadAgentRuns();
            } catch (error) {
                this.agentsError = 'اجرا ناموفق بود: ' + error.message;
            }
        },

        async pauseAgentRun(runId) {
            this.agentsError = '';
            try {
                const response = await fetch('/api/agents/runs/' + encodeURIComponent(runId) + '/pause', { method: 'POST' });
                if (!response.ok) {
                    const detail = await response.json().catch(() => ({}));
                    throw new Error(detail.detail || ('HTTP ' + response.status));
                }
                await this.loadAgentRuns();
            } catch (error) {
                this.agentsError = 'توقف ناموفق بود: ' + error.message;
            }
        },

        async resumeAgentRun(runId) {
            this.agentsError = '';
            try {
                const response = await fetch('/api/agents/runs/' + encodeURIComponent(runId) + '/resume', { method: 'POST' });
                if (!response.ok) {
                    const detail = await response.json().catch(() => ({}));
                    throw new Error(detail.detail || ('HTTP ' + response.status));
                }
                await this.loadAgentRuns();
            } catch (error) {
                this.agentsError = 'ادامه ناموفق بود: ' + error.message;
            }
        },

        async cancelAgentRun(runId) {
            this.agentsError = '';
            try {
                const response = await fetch('/api/agents/runs/' + encodeURIComponent(runId) + '/cancel', { method: 'POST' });
                if (!response.ok) {
                    const detail = await response.json().catch(() => ({}));
                    throw new Error(detail.detail || ('HTTP ' + response.status));
                }
                await this.loadAgentRuns();
            } catch (error) {
                this.agentsError = 'لغو ناموفق بود: ' + error.message;
            }
        },

        async loadOrchestrationPlans() {
            this.orchestrationLoading = true;
            this.orchestrationError = '';
            try {
                const response = await fetch('/api/orchestration/plans');
                if (!response.ok) throw new Error('HTTP ' + response.status);
                const data = await response.json();
                this.orchestrationPlans = data.plans || [];
            } catch (error) {
                this.orchestrationError = 'بارگذاری برنامه‌های سازمان‌دهی ناموفق بود: ' + error.message;
            } finally {
                this.orchestrationLoading = false;
            }
        },

        async createOrchestrationGoalAndPlan() {
            this.orchestrationError = '';
            try {
                const goalResponse = await fetch('/api/orchestration/goals', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        description: this.orchestrationGoalForm.description,
                        success_criteria: this.orchestrationGoalForm.success_criteria || this.orchestrationGoalForm.description,
                        data_scopes: [{
                            domain: 'knowledge',
                            scope_type: 'user',
                            scope_id: this.orchestrationGoalForm.scope_id || 'local-user',
                            owner_id: 'local-user',
                        }],
                        tool_scopes: ['knowledge_search'],
                    })
                });
                if (!goalResponse.ok) {
                    const detail = await goalResponse.json().catch(() => ({}));
                    throw new Error(detail.detail || ('HTTP ' + goalResponse.status));
                }
                const goal = await goalResponse.json();
                const planResponse = await fetch('/api/orchestration/plans', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ goal_id: goal.goal_id, strategy: 'deterministic_template' })
                });
                if (!planResponse.ok) {
                    const detail = await planResponse.json().catch(() => ({}));
                    throw new Error(detail.detail || ('HTTP ' + planResponse.status));
                }
                this.orchestrationGoalForm.description = '';
                await this.loadOrchestrationPlans();
            } catch (error) {
                this.orchestrationError = 'ایجاد هدف/برنامه ناموفق بود: ' + error.message;
            }
        },

        async executeOrchestrationPlan(planId) {
            this.orchestrationError = '';
            try {
                const response = await fetch('/api/orchestration/plans/' + encodeURIComponent(planId) + '/execute', { method: 'POST' });
                if (!response.ok) {
                    const detail = await response.json().catch(() => ({}));
                    throw new Error(detail.detail || ('HTTP ' + response.status));
                }
                await this.loadOrchestrationPlans();
                await this.loadOrchestrationPlanDetail(planId);
            } catch (error) {
                this.orchestrationError = 'اجرای برنامه ناموفق بود: ' + error.message;
            }
        },

        async cancelOrchestrationPlan(planId) {
            this.orchestrationError = '';
            try {
                const response = await fetch('/api/orchestration/plans/' + encodeURIComponent(planId) + '/cancel', { method: 'POST' });
                if (!response.ok) {
                    const detail = await response.json().catch(() => ({}));
                    throw new Error(detail.detail || ('HTTP ' + response.status));
                }
                await this.loadOrchestrationPlans();
            } catch (error) {
                this.orchestrationError = 'لغو برنامه ناموفق بود: ' + error.message;
            }
        },

        async reconcileOrchestrationPlan(planId) {
            this.orchestrationError = '';
            try {
                const response = await fetch('/api/orchestration/plans/' + encodeURIComponent(planId) + '/reconcile', { method: 'POST' });
                if (!response.ok) {
                    const detail = await response.json().catch(() => ({}));
                    throw new Error(detail.detail || ('HTTP ' + response.status));
                }
                await this.loadOrchestrationPlans();
            } catch (error) {
                this.orchestrationError = 'بازیابی برنامه ناموفق بود: ' + error.message;
            }
        },

        async loadOrchestrationPlanDetail(planId) {
            this.orchestrationError = '';
            try {
                const response = await fetch('/api/orchestration/plans/' + encodeURIComponent(planId));
                if (!response.ok) throw new Error('HTTP ' + response.status);
                this.orchestrationPlanDetail = await response.json();
            } catch (error) {
                this.orchestrationError = 'بارگذاری جزئیات برنامه ناموفق بود: ' + error.message;
            }
        },

        async decideApproval(approvalId, decision) {
            this.agentsError = '';
            try {
                const response = await fetch('/api/permissions/approvals/' + encodeURIComponent(approvalId) + '/' + decision, { method: 'POST' });
                if (!response.ok) {
                    const detail = await response.json().catch(() => ({}));
                    throw new Error(detail.detail || ('HTTP ' + response.status));
                }
                await this.loadAgentRuns();
            } catch (error) {
                this.agentsError = 'تصمیم تأیید ناموفق بود: ' + error.message;
            }
        },

        async generateOfflineReport() {
            if (this.intelligenceReportLoading) return;
            this.intelligenceReportLoading = true;
            this.intelligenceReportError = '';
            const provider = this.settings.active_provider;
            try {
                const response = await fetch('/api/intelligence/reports/offline?provider_id=' + encodeURIComponent(provider), { method: 'POST' });
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'تولید گزارش آفلاین ناموفق بود.');
                this.intelligenceReport = data;
            } catch (error) {
                this.intelligenceReportError = error.message;
            } finally {
                this.intelligenceReportLoading = false;
            }
        },

        async onProviderChange() {
            this.connectionResult = null;
            this.providerQuota = null;
            this.catalogSyncResult = null;
            // Never leave the previous provider's options visible during a provider switch.
            this.availableModels = [];
            this.modelsError = '';
            await this.loadProviderCapabilities();
            await this.refreshModels();
            await this.loadLatestIntelligenceReport();
        },

        async checkProviderConnection() {
            this.connectionLoading = true;
            this.connectionResult = null;
            try {
                // Persist the currently edited provider settings before probing them.
                const saveResponse = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.settings)
                });
                const saved = await saveResponse.json();
                if (!saveResponse.ok) throw new Error(saved.detail || 'ذخیره تنظیمات ناموفق بود.');
                this.settings = saved.config;
                this.updateProviderKeyHints();

                const provider = this.settings.active_provider;
                const response = await fetch('/api/providers/' + encodeURIComponent(provider) + '/connection', { method: 'POST', cache: 'no-store' });
                const result = await response.json();
                if (!response.ok) throw new Error(result.detail || 'بررسی اتصال ناموفق بود.');
                this.connectionResult = result;
                this.intelligenceReport = result.intelligence_report || this.intelligenceReport;
                if (result.status === 'reachable') {
                    this.catalogSyncResult = result.catalog_sync || null;
                    await this.loadProviderCapabilities();
                    await this.refreshModels();
                    await this.loadOperationalReport();
                } else {
                    await this.loadOperationalReport();
                }
            } catch (error) {
                this.connectionResult = {
                    status: 'error',
                    error: { message: error.message || 'بررسی اتصال ناموفق بود.' }
                };
            } finally {
                this.connectionLoading = false;
            }
        },

        async loadProviderCapabilities() {
            this.providerCapabilities = null;
            const provider = this.settings.active_provider;
            try {
                // The operator catalog is local metadata; it must never trigger network discovery.
                const response = await fetch(`/api/providers/${encodeURIComponent(provider)}/catalog`);
                if (!response.ok) throw new Error('بارگذاری کاتالوگ اپراتور ناموفق بود.');
                this.providerCapabilities = await response.json();
                this.providerCatalogSnapshot = this.providerCapabilities.storage || null;
            } catch (error) {
                console.warn('Operator catalog could not be loaded:', error);
            }
        },
        async refreshProviderQuota() {
            this.providerQuota = null;
            const provider = this.settings.active_provider;
            try {
                const response = await fetch(`/api/providers/${encodeURIComponent(provider)}/quota`);
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'دریافت وضعیت سهمیه ناموفق بود.');
                this.providerQuota = data;
                await this.loadOperationalReport();
            } catch (error) {
                this.providerQuota = { status: 'error', message: error.message };
            }
        },
        async refreshModels() {
            this.modelsLoading = true;
            this.modelsError = '';
            const provider = this.settings.active_provider;
            const config = this.settings.providers_config[provider] ||= {};
            const defaultModel = config.model || '';
            try {
                // Model selection reads the durable catalog; network discovery is an explicit sync action.
                const response = await fetch(`/api/providers/${encodeURIComponent(provider)}/models`);
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'خواندن کاتالوگ ذخیره‌شده ناموفق بود.');
                const storedModels = data.models || [];
                this.availableModels = storedModels.length ? storedModels : (defaultModel ? [defaultModel] : []);
                if (storedModels.length && !storedModels.includes(config.model)) {
                    // Do not silently change the user's selected model; retain it until they choose another.
                    this.modelsError = 'مدل انتخاب‌شده فعلاً در کاتالوگ زنده دیده نمی‌شود؛ انتخاب فعلی حفظ شده است.';
                } else if (!storedModels.length) {
                    this.modelsError = 'هنوز کاتالوگ زنده‌ای برای این Provider ذخیره نشده است. از «دریافت/همگام‌سازی کاتالوگ» استفاده کنید.';
                }
            } catch (error) {
                this.modelsError = error.message;
                this.availableModels = defaultModel ? [defaultModel] : [];
            } finally {
                this.modelsLoading = false;
            }
        },

        async syncProviderCatalog() {
            if (this.catalogSyncLoading) return;
            this.catalogSyncLoading = true;
            this.catalogSyncResult = null;
            const provider = this.settings.active_provider;
            try {
                const response = await fetch(`/api/providers/${encodeURIComponent(provider)}/catalog/sync`, { method: 'POST' });
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'همگام‌سازی کاتالوگ ناموفق بود.');
                this.catalogSyncResult = data.sync;
                this.providerCatalogSnapshot = data.catalog;
                this.intelligenceReport = data.report || data.connection?.intelligence_report || this.intelligenceReport;
                await this.loadProviderCapabilities();
                await this.refreshModels();
                await this.loadOperationalReport();
            } catch (error) {
                // A failed refresh does not clear the previously stored catalog.
                this.catalogSyncResult = { status: 'failed', error: error.message };
                this.modelsError = error.message;
            } finally {
                this.catalogSyncLoading = false;
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
            try {
                const request = await fetch('/api/permissions/approvals/avatar-delete', { method: 'POST' });
                const approval = await request.json();
                if (!request.ok) throw new Error(approval.detail || 'ثبت درخواست تأیید ناموفق بود.');
                const decision = await fetch(`/api/permissions/approvals/${encodeURIComponent(approval.approval_id)}/approve`, { method: 'POST' });
                const decisionData = await decision.json();
                if (!decision.ok) throw new Error(decisionData.detail || 'تأیید حذف ناموفق بود.');
                const response = await fetch(`/api/profile/avatar?approval_id=${encodeURIComponent(approval.approval_id)}`, { method: 'DELETE' });
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'حذف تصویر ناموفق بود.');
                this.profile = { ...this.profile, ...data };
            } catch (error) {
                alert(error.message);
            }
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
                const request = await fetch(`/api/permissions/approvals/session-delete/${session.id}`, { method: 'POST' });
                const approval = await request.json();
                if (!request.ok) throw new Error(approval.detail || 'ثبت درخواست تأیید ناموفق بود.');
                const decision = await fetch(`/api/permissions/approvals/${encodeURIComponent(approval.approval_id)}/approve`, { method: 'POST' });
                const decisionData = await decision.json();
                if (!decision.ok) throw new Error(decisionData.detail || 'تأیید حذف ناموفق بود.');
                const response = await fetch(`/api/sessions/${session.id}?approval_id=${encodeURIComponent(approval.approval_id)}`, { method: 'DELETE' });
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

        async sendMessage(retry = null) {
            if (this.isLoading) return;

            const isRetry = Boolean(retry);
            if (!isRetry && !this.inputMessage.trim()) return;
            const userText = isRetry ? retry.message : this.inputMessage;
            const sessionId = isRetry ? retry.sessionId : this.currentSessionId;
            const request_id = isRetry
                ? retry.requestId
                : 'req_' + (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, '') : Date.now().toString(36) + Math.random().toString(36).slice(2));
            let aiMsgIndex;

            if (isRetry) {
                if (!this.pendingRetry || this.pendingRetry.requestId !== request_id || sessionId !== this.currentSessionId) return;
                aiMsgIndex = retry.assistantIndex;
                this.messages[aiMsgIndex].content = 'در حال بازیابی پاسخ قبلی...';
                this.messages[aiMsgIndex].model = 'در حال اتصال مجدد...';
                this.pendingRetry = null;
            } else {
                this.inputMessage = '';
                this.messages.push({ role: 'user', content: userText });
                aiMsgIndex = this.messages.push({ role: 'assistant', content: '', model: '' }) - 1;
            }

            this.isLoading = true;
            this.streamingSessionId = sessionId;
            this.activeRequestId = request_id;
            this.scrollToBottom();
            let terminalReceived = false;
            let retryableFailure = true;

            try {
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ session_id: sessionId, message: userText, request_id })
                });
                if (!response.ok) {
                    retryableFailure = false;
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
                    const events = buffer.split('\\n\\n');
                    buffer = events.pop() || '';
                    for (const event of events) {
                        const line = event.split('\\n').find(part => part.startsWith('data:'));
                        if (!line) continue;
                        const data = JSON.parse(line.slice(5).trim());
                        // Legacy protocol events and versioned Phase 8 events share one parser.
                        if (data.type === 'meta') this.messages[aiMsgIndex].model = data.model;
                        else if (data.type === 'chunk') {
                            this.messages[aiMsgIndex].content += data.content;
                            this.scrollToBottom();
                        } else if (data.type === 'accepted' || data.type === 'progress') {
                            if (!this.messages[aiMsgIndex].content) this.messages[aiMsgIndex].model = 'در حال پردازش...';
                        } else if (data.type === 'status') {
                            const detail = data.data || {};
                            if (detail.provider_id && detail.model) {
                                this.messages[aiMsgIndex].model = detail.provider_id + ' / ' + detail.model;
                            }
                        } else if (data.type === 'validation') {
                            const state = (data.data || {}).state;
                            if (state === 'partial') this.messages[aiMsgIndex].model = 'پاسخ بخشی تأیید شد';
                        } else if (data.type === 'approval_required') {
                            const detail = data.data || {};
                            this.messages[aiMsgIndex].approval = detail;
                            this.loadConversationApprovalDetails(this.messages[aiMsgIndex], detail.approval_id);
                            this.messages[aiMsgIndex].model = 'در انتظار تأیید شما';
                            this.messages[aiMsgIndex].content += '\\n\\n🔐 برای ادامهٔ اجرای این کار، تأیید شما لازم است.';
                            this.scrollToBottom();
                        } else if (data.type === 'final') {
                            terminalReceived = true;
                            const detail = data.data || {};
                            this.messages[aiMsgIndex].content = detail.content !== undefined ? detail.content : this.messages[aiMsgIndex].content;
                            if (detail.provenance && detail.provenance.provider_id) {
                                this.messages[aiMsgIndex].model = detail.provenance.provider_id + ' / ' + (detail.provenance.model_used || '');
                            }
                            if (detail.status && detail.status !== 'completed') {
                                this.messages[aiMsgIndex].content += '\\n\\n⚠️ وضعیت اجرا: ' + detail.status;
                            }
                        } else if (data.type === 'cancelled') {
                            terminalReceived = true;
                            this.messages[aiMsgIndex].content += '\\n\\n⏹ اجرا لغو شد.';
                        } else if (data.type === 'error') {
                            terminalReceived = true;
                            const detail = data.data || {};
                            this.messages[aiMsgIndex].content += '\\n\\n❌ خطا: ' + (detail.message || detail.content || 'نامشخص');
                        }
                    }
                }
                if (!terminalReceived && retryableFailure) {
                    this.pendingRetry = { sessionId, message: userText, requestId: request_id, assistantIndex: aiMsgIndex };
                    this.messages[aiMsgIndex].content += '\\n\\n⚠️ ارتباط پیش از دریافت نتیجه نهایی قطع شد. می‌توانی با همان شناسه درخواست دوباره تلاش کنی.';
                } else {
                    this.pendingRetry = null;
                    await this.loadSessions();
                    // This endpoint serves local metadata only; it does not call provider model catalogs.
                    await this.loadProviderCapabilities();
                }
            } catch (error) {
                if (retryableFailure) {
                    this.pendingRetry = { sessionId, message: userText, requestId: request_id, assistantIndex: aiMsgIndex };
                    this.messages[aiMsgIndex].content = 'ارتباط قطع شد: ' + error.message + '\\n\\nمی‌توانی با همان شناسه درخواست دوباره تلاش کنی.';
                } else {
                    this.messages[aiMsgIndex].content = 'خطا در درخواست: ' + error.message;
                    this.pendingRetry = null;
                }
            } finally {
                this.isLoading = false;
                this.streamingSessionId = null;
                this.activeRequestId = null;
            }
        },

        async retryPendingMessage() {
            if (!this.pendingRetry || this.isLoading) return;
            return this.sendMessage(this.pendingRetry);
        },

        async loadConversationApprovalDetails(message, approvalId) {
            try {
                const response = await fetch('/api/permissions/approvals?limit=500');
                if (!response.ok) return;
                const data = await response.json();
                const approval = (data.approvals || []).find(item => item.approval_id === approvalId);
                if (!approval) return;
                const resource = approval.resource || {};
                const scope = approval.scope || {};
                message.approvalSummary = [
                    approval.operation || 'operation',
                    (resource.type || 'resource') + ':' + (resource.id || 'unknown'),
                    (scope.type || 'scope') + ':' + (scope.id || 'unknown')
                ].join(' · ');
            } catch (error) {
                // The approval action remains available even if its summary cannot be loaded.
            }
        },

        async decideConversationApproval(message, approve) {
            const approval = message && message.approval;
            if (!approval || message.approvalBusy) return;
            message.approvalBusy = true;
            message.approvalError = '';
            try {
                const action = approve ? 'approve' : 'reject';
                const decision = await fetch(
                    '/api/permissions/approvals/' + encodeURIComponent(approval.approval_id) + '/' + action,
                    { method: 'POST' }
                );
                const decisionBody = await decision.json().catch(() => ({}));
                if (!decision.ok) {
                    // Replayed approval events may outlive the first successful click.
                    // Accept only the exact already-recorded decision, never a different one.
                    const listResponse = await fetch('/api/permissions/approvals?limit=100');
                    const listBody = await listResponse.json().catch(() => ({}));
                    const recorded = (listBody.approvals || []).find(item => item.approval_id === approval.approval_id);
                    const expectedStatus = approve ? 'approved' : 'rejected';
                    if (recorded?.status !== expectedStatus) {
                        throw new Error(decisionBody.detail || 'ثبت تصمیم تأیید ناموفق بود.');
                    }
                }

                const resume = await fetch(
                    '/api/agents/runs/' + encodeURIComponent(approval.run_id) + '/resume',
                    { method: 'POST' }
                );
                const resumeBody = await resume.json().catch(() => ({}));
                if (!resume.ok) throw new Error(resumeBody.detail || 'آماده‌سازی ادامهٔ اجرا ناموفق بود.');

                if (approve) {
                    const runStatus = resumeBody.run?.status;
                    if (runStatus === 'paused') {
                        const execute = await fetch(
                            '/api/agents/runs/' + encodeURIComponent(approval.run_id) + '/execute',
                            { method: 'POST' }
                        );
                        const executeBody = await execute.json().catch(() => ({}));
                        if (!execute.ok) throw new Error(executeBody.detail || 'ادامهٔ اجرای عامل ناموفق بود.');
                    }
                    message.content += '\\n\\n✅ تأیید ثبت شد؛ اجرای همان عامل از نقطهٔ توقف ادامه یافت.';
                } else {
                    message.content += '\\n\\n⛔ درخواست رد شد و اجرای وابسته لغو شد.';
                }
                message.approval = null;
                this.scrollToBottom();
            } catch (error) {
                message.approvalError = error.message;
            } finally {
                message.approvalBusy = false;
            }
        },

        async cancelMessage() {
            if (!this.streamingSessionId || !this.activeRequestId) return;
            try {
                const response = await fetch('/api/chat/cancel', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        session_id: this.streamingSessionId,
                        request_id: this.activeRequestId
                    })
                });
                if (!response.ok) {
                    const error = await response.json().catch(() => ({}));
                    throw new Error(error.detail || 'لغو درخواست ناموفق بود.');
                }
            } catch (error) {
                const active = this.messages[this.messages.length - 1];
                if (active && active.role === 'assistant') {
                    active.content += '\\n\\n⚠️ ' + error.message;
                }
            }
        }
    };
}
