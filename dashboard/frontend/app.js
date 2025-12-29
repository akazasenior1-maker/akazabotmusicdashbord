const API_URL = window.location.protocol === 'file:' ? 'http://localhost:8000' : window.location.origin;
let currentToken = localStorage.getItem('discord_token');
let currentGuildId = null;
let ws = null;

let currentSongDuration = 0;
let lastSyncElapsed = 0;
let isPaused = false;
let stats = { total_played: 0, tracks: {} };
let isDraggingVolume = false;
let eqDebounceTimer = null;
let botStatusInterval = null;
let wsReconnectAttempts = 0;
const MAX_WS_RECONNECT_S = 30;
let lastSyncTime = 0;

function debounce(func, wait) {
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(eqDebounceTimer);
            func(...args);
        };
        clearTimeout(eqDebounceTimer);
        eqDebounceTimer = setTimeout(later, wait);
    };
}

// Waveform Animation state
let waveformArr = [];
const canvas = document.getElementById('waveform-canvas');
const ctx = canvas ? canvas.getContext('2d') : null;

// Init
window.onload = async () => {
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('token');

    if (token) {
        currentToken = token;
        localStorage.setItem('discord_token', token);
        window.history.replaceState({}, document.title, "/");
    }

    if (currentToken) {
        showDashboard();
        startBotStatusPolling();
    } else {
        showLogin();
    }

    if (window.location.protocol === 'file:') {
        alert("CRITICAL UPLINK ERROR:\nYou are opening the file directly. Please visit http://localhost:8000 in your browser after starting the bot.");
    }

    if (canvas) setupWaveform();
};

function showLogin() {
    document.getElementById('login-screen').classList.add('active');
    document.getElementById('dashboard-screen').classList.remove('active');
}

async function showDashboard() {
    document.getElementById('login-screen').classList.remove('active');
    document.getElementById('dashboard-screen').classList.add('active');

    try {
        const user = await fetchAPI('/api/user');
        document.getElementById('user-name').textContent = user.username;
        const avatarUrl = user.avatar
            ? `https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png`
            : `https://cdn.discordapp.com/embed/avatars/0.png`;
        document.getElementById('user-avatar').src = avatarUrl;

        const servers = await fetchAPI('/api/servers');
        const isAdmin = servers.some(s => (s.permissions & 0x8) === 0x8); // Check for ADMINISTRATOR permission bit
        const systemTab = document.querySelector('nav a[href="#system-control"]');
        if (systemTab) {
            systemTab.style.display = isAdmin ? 'flex' : 'none';
        }

        renderServers(servers);
    } catch (err) {
        console.error("Auth error", err);
        logout();
    }
}

async function renderServers(servers) {
    const container = document.getElementById('server-list');
    container.innerHTML = '<div class="loader-spinner neon-text-blue"><i class="fas fa-atom fa-spin"></i> Initializing...</div>';

    try {
        const servers = await fetchAPI('/api/servers');
        container.innerHTML = '';

        if (servers.length === 0) {
            container.innerHTML = '<div class="no-access glass neon-border"><i class="fas fa-lock"></i> <p>ACCESS DENIED: Required role "⚛ | 𝐃𝐉𝐌𝐀𝐒𝐓𝐄𝐑" not detected.</p></div>';
            return;
        }

        servers.forEach(server => {
            const card = document.createElement('div');
            card.className = 'server-card glass neon-border';
            if (!server.has_access && server.bot_in) card.classList.add('locked');

            const iconUrl = server.icon
                ? `https://cdn.discordapp.com/icons/${server.id}/${server.icon}.png`
                : 'https://cdn.discordapp.com/embed/avatars/0.png';

            let actionHtml = '';
            if (server.bot_in) {
                if (server.has_access) {
                    if (server.role_missing) {
                        actionHtml = `
                            <button class="btn-neon-main" id="btn-manage-${server.id}">OPEN COMMAND PANEL</button>
                            <div class="setup-warning">
                                <i class="fas fa-exclamation-triangle neon-text-yellow"></i> ROLE MISSING
                                <button class="btn-neon-outline btn-small" onclick="createRole(this, '${server.id}')">CREATE NOW</button>
                            </div>
                        `;
                    } else {
                        actionHtml = `<button class="btn-neon-main" id="btn-manage-${server.id}">OPEN COMMAND PANEL</button>`;
                    }
                } else {
                    actionHtml = `
                        <div class="locked-msg neon-text-red">
                            <i class="fas fa-lock"></i> MISSING ROLE
                        </div>
                        <p class="role-instruction">Ask owner for role:</p>
                        <button class="btn-neon-outline copy-role-btn" onclick="copyRole(this)">
                            <i class="fas fa-copy"></i> ⚛ | 𝐃𝐉𝐌𝐀𝐒𝐓𝐄𝐑
                        </button>
                    `;
                }
            } else {
                actionHtml = '<button class="btn-neon-secondary invite-btn">INVITE STATION</button>';
            }

            card.innerHTML = `
                <img class="server-icon" src="${iconUrl}" alt="">
                <h3 class="neon-text-blue">${server.name}</h3>
                ${actionHtml}
            `;

            if (server.bot_in && server.has_access) {
                card.onclick = (e) => {
                    if (e.target.tagName === 'BUTTON' || e.target.closest('button')) return;
                    const btn = document.getElementById('btn-manage-' + server.id);
                    btn.innerHTML = '<i class="fas fa-atom fa-spin"></i> SYNCING...';
                    openControlPanel(server);
                };
                // Make the button clickable too
                const btn = card.querySelector(`#btn-manage-${server.id}`);
                if (btn) btn.onclick = () => {
                    btn.innerHTML = '<i class="fas fa-atom fa-spin"></i> SYNCING...';
                    openControlPanel(server);
                };
            } else if (!server.bot_in) {
                card.querySelector('.invite-btn').onclick = (e) => {
                    e.stopPropagation();
                    const clientId = "1451230914561577232";
                    window.open(`https://discord.com/api/oauth2/authorize?client_id=${clientId}&permissions=8&scope=bot%20applications.commands`, '_blank');
                };
            }
            container.appendChild(card);
        });
    } catch (err) {
        container.innerHTML = `<p class="neon-text-red">UPLINK ERROR: ${err.message}</p>`;
    }
}

function openControlPanel(server) {
    currentGuildId = server.id;
    document.getElementById('current-server-name').textContent = server.name;
    showPage('control');
    connectWebSocket(server.id);
    updateInitialStatus();
}

function connectWebSocket(guildId) {
    if (ws) ws.close();
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws/${guildId}`);

    ws.onopen = () => {
        console.log("WS Uplink Established");
        wsReconnectAttempts = 0;
        document.querySelector('.player-card-neon').classList.add('visualizing');
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        updateUI(data);
    };

    ws.onclose = () => {
        if (currentGuildId === guildId) {
            const delay = Math.min(Math.pow(2, wsReconnectAttempts) * 1000, MAX_WS_RECONNECT_S * 1000);
            console.log(`WS connection lost. Retrying in ${delay / 1000}s...`);
            wsReconnectAttempts++;
            setTimeout(() => connectWebSocket(guildId), delay);
        }
        document.querySelector('.player-card-neon').classList.remove('visualizing');
    };

    ws.onerror = (err) => {
        console.error("WS Engine Error", err);
    };
}

async function updateInitialStatus() {
    try {
        const status = await fetchAPI(`/api/server/${currentGuildId}/status`);
        updateUI(status);
    } catch (err) {
        console.error("Initial status err", err);
    }
}

function updateUI(status) {
    // Connection Status
    const statusDot = document.getElementById('bot-channel-status');
    if (status.connected) {
        statusDot.innerHTML = `<i class="fas fa-satellite status-dot neon-text-blue"></i> UPLINK ACTIVE: ${status.channel}`;
        document.querySelector('.player-card-neon').classList.add('visualizing');
    } else {
        statusDot.innerHTML = `<i class="fas fa-user-slash status-dot neon-text-red"></i> NO TARGET CHANNEL DETECTED`;
        document.querySelector('.player-card-neon').classList.remove('visualizing');
    }

    // Now Playing
    if (status.current_song) {
        document.getElementById('song-title').textContent = status.current_song.title;
        document.getElementById('song-requester').querySelector('span').textContent = status.current_song.requester;
        document.getElementById('song-thumbnail').src = status.current_song.thumbnail || 'https://via.placeholder.com/300/1a1a1a/00f2ff?text=AKAZA+MUSIC';

        currentSongDuration = status.current_song.duration;
        document.querySelector('.time-total').textContent = formatTime(currentSongDuration);

        lastSyncElapsed = status.elapsed || 0;
        lastSyncTime = Date.now();
        isPaused = status.is_paused;

        updateProgressUI();
        startProgressTimer();
    } else {
        stopProgressTimer();
        document.getElementById('song-title').textContent = "STANDBY MODE";
        document.getElementById('song-requester').querySelector('span').textContent = "None";
        document.getElementById('song-thumbnail').src = 'https://via.placeholder.com/300/1a1a1a/00f2ff?text=AKAZA+MUSIC';
        document.querySelector('.time-total').textContent = "0:00";
        updateProgressUI(0);
        document.querySelector('.time-current').textContent = "0:00";
    }

    // Controls
    const pauseBtn = document.getElementById('btn-pause');
    pauseBtn.innerHTML = status.is_paused ? '<i class="fas fa-play"></i>' : '<i class="fas fa-pause"></i>';

    // Settings (Don't update while dragging to prevent fighting the server)
    if (!isDraggingVolume) {
        document.getElementById('volume-range').value = status.volume;
        document.getElementById('volume-val').textContent = `${status.volume}%`;
    }
    document.getElementById('bass-boost-toggle').checked = status.bass_boost;
    document.getElementById('autoplay-toggle').checked = status.auto_play;

    // Stats
    if (status.stats) {
        document.getElementById('stat-total-played').textContent = status.stats.total_played || 0;
        document.getElementById('stat-listeners').textContent = status.listeners || 0;

        const tracks = status.stats.tracks || {};
        const topTrack = Object.keys(tracks).reduce((a, b) => tracks[a] > tracks[b] ? a : b, "-");
        document.getElementById('stat-top-track').textContent = topTrack;
    }

    // EQ
    if (status.eq_gains) {
        if (document.getElementById('eq-low')) document.getElementById('eq-low').value = status.eq_gains.low || 0;
        if (document.getElementById('eq-mid')) document.getElementById('eq-mid').value = status.eq_gains.mid || 0;
        if (document.getElementById('eq-high')) document.getElementById('eq-high').value = status.eq_gains.high || 0;
    }

    // Queue
    renderQueue(status.queue);

    // History
    if (status.history) renderHistory(status.history);
}

function renderHistory(history) {
    const hList = document.getElementById('history-list');
    if (!hList) return;
    if (!history || history.length === 0) {
        hList.innerHTML = '<div class="empty-msg glass neon-border"><i class="fas fa-ghost"></i><p>No past signals detected yet.</p></div>';
        return;
    }
    hList.innerHTML = '';
    history.forEach(item => {
        const div = document.createElement('div');
        div.className = 'history-item glass neon-border';
        const thumb = item.thumbnail || 'https://via.placeholder.com/300/1a1a1a/00f2ff?text=AKAZA+MUSIC';
        div.innerHTML = `
            <img src="${thumb}" class="history-thumb" alt="">
            <div class="history-info">
                <h4 class="truncate">${item.title}</h4>
                <p><i class="fas fa-user-astronaut"></i> ${item.requester}</p>
            </div>
        `;
        hList.appendChild(div);
    });
}

function renderQueue(queue) {
    const qList = document.getElementById('queue-list');
    qList.innerHTML = '';
    if (queue.length === 0) {
        qList.innerHTML = '<div class="empty-q neon-text-purple">QUEUE SIGNAL EMPTY</div>';
        return;
    }
    queue.forEach((item, index) => {
        const div = document.createElement('div');
        div.className = 'q-item-neon';
        div.innerHTML = `
            <span class="q-index">${index + 1}</span>
            <div class="q-info">
                <div class="q-title truncate">${item.title}</div>
                <div class="q-req">${item.requester}</div>
            </div>
            <span class="q-time">${formatTime(item.duration)}</span>
            <div class="q-action">
                <button class="btn-delete-q" onclick="deleteQueueItem(${index})"><i class="fas fa-trash"></i></button>
            </div>
        `;
        qList.appendChild(div);
    });
}

// Handlers
async function handlePlay() {
    const input = document.getElementById('play-input');
    const query = input.value.trim();
    if (!query) return;

    input.value = '';
    const originalPlaceholder = input.placeholder;
    input.placeholder = '🛰️ INJECTING SIGNAL...';
    try {
        await sendControl('play', { query });
        input.placeholder = '🛰️ SYNCING IN 5s...';
        setTimeout(async () => {
            await updateInitialStatus();
            input.placeholder = originalPlaceholder;
        }, 5000);
    } catch (err) {
        input.placeholder = '⚠️ SIGNAL INTERRUPTED';
        setTimeout(() => input.placeholder = originalPlaceholder, 3000);
    }
}

document.getElementById('btn-play-submit').onclick = handlePlay;
document.getElementById('play-input').onkeypress = (e) => { if (e.key === 'Enter') handlePlay(); };
document.getElementById('btn-pause').onclick = () => sendControl('toggle');
document.getElementById('btn-skip').onclick = () => sendControl('skip');
document.getElementById('btn-stop').onclick = () => sendControl('stop');
document.getElementById('btn-leave').onclick = () => sendControl('leave');
document.getElementById('volume-range').onchange = (e) => sendControl('volume', { level: parseInt(e.target.value) });
document.getElementById('bass-boost-toggle').onchange = (e) => sendControl('bass_boost', { enabled: e.target.checked });
document.getElementById('autoplay-toggle').onchange = (e) => sendControl('auto_play', { enabled: e.target.checked });
document.getElementById('clear-queue').onclick = () => sendControl('stop');

// Settings Save
document.querySelector('.btn-save').onclick = async () => {
    const vol = document.querySelector('#settings-page input[type="range"]').value;
    const btn = document.querySelector('.btn-save');
    const originalText = btn.textContent;
    btn.innerHTML = '<i class="fas fa-atom fa-spin"></i> CONFIGURING...';

    try {
        await fetch(`${API_URL}/api/server/${currentGuildId}/settings?token=${currentToken}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ volume: parseInt(vol) })
        });
        btn.innerHTML = '<i class="fas fa-check"></i> ENGINE CALIBRATED';
        setTimeout(() => btn.textContent = originalText, 2000);
    } catch (err) {
        btn.textContent = 'UPLINK ERROR';
        setTimeout(() => btn.textContent = originalText, 2000);
    }
};

async function deleteQueueItem(index) {
    await sendControl('delete_queue', { index });
}

async function sendControl(action, params = {}) {
    if (action === 'toggle') {
        const isPausedBtn = document.getElementById('btn-pause').innerHTML.includes('fa-play');
        action = isPausedBtn ? 'resume' : 'pause';
    }

    // Identify triggering element if possible (for visual feedback)
    let triggerBtn = null;
    if (action === 'play') triggerBtn = document.getElementById('btn-play-submit');
    else if (action === 'pause' || action === 'resume') triggerBtn = document.getElementById('btn-pause');
    else if (action === 'skip') triggerBtn = document.getElementById('btn-skip');
    else if (action === 'stop') triggerBtn = document.getElementById('btn-stop');
    else if (action === 'leave') triggerBtn = document.getElementById('btn-leave');

    if (triggerBtn) {
        triggerBtn.classList.add('loading');
        triggerBtn.disabled = true;
    }

    try {
        params.token = currentToken;
        const res = await fetch(`${API_URL}/api/server/${currentGuildId}/control?action=${action}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params)
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Signal Rejected");
        }

        // Optimistic UI for some actions
        if (action === 'pause') isPaused = true;
        if (action === 'resume') isPaused = false;

    } catch (err) {
        console.error(`Control Error [${action}]:`, err);
        addSystemLog(`Command Failed: ${err.message}`, "error");
        alert(`UPLINK FAILURE: ${err.message}`);
    } finally {
        if (triggerBtn) {
            setTimeout(() => {
                triggerBtn.classList.remove('loading');
                triggerBtn.disabled = false;
            }, 500); // Small cooldown to prevent spam
        }
    }
}

// Stats Persistence (Client-side cache for smoother updates)
function formatTime(seconds) {
    if (!seconds || seconds < 0) return '0:00';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s < 10 ? '0' : ''}${s}`;
}

// Progress Engine
let progressTimer = null;
function updateProgressUI(forcedElapsed = null) {
    const elapsed = forcedElapsed !== null ? forcedElapsed : (isPaused ? lastSyncElapsed : lastSyncElapsed + (Date.now() - lastSyncTime) / 1000);
    const safeElapsed = Math.min(elapsed, currentSongDuration);
    const percent = currentSongDuration > 0 ? (safeElapsed / currentSongDuration) * 100 : 0;

    const fill = document.getElementById('progress-fill');
    const timeCurr = document.querySelector('.time-current');

    if (fill) fill.style.width = `${percent}%`;
    if (timeCurr) timeCurr.textContent = formatTime(safeElapsed);
}

function startProgressTimer() {
    if (progressTimer) clearInterval(progressTimer);
    progressTimer = setInterval(() => {
        if (isPaused) return;
        updateProgressUI();
    }, 100); // Smoother high-frequency updates
}

function stopProgressTimer() {
    if (progressTimer) clearInterval(progressTimer);
    progressTimer = null;
}

// Navigation
function showPage(pageId) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-links a').forEach(a => a.classList.remove('active'));
    document.getElementById(`${pageId}-page`).classList.add('active');

    const navLink = Array.from(document.querySelectorAll('.nav-links a')).find(a => a.textContent.toLowerCase().includes(pageId));
    if (navLink) navLink.classList.add('active');
}

// UI Helper for safe handler attachment
function safeOnclick(id, handler) {
    const el = document.getElementById(id);
    if (el) el.onclick = handler;
}

safeOnclick('logout-btn', logout);
safeOnclick('login-btn', () => {
    console.log("Initiating Discord Auth...");
    window.location.href = API_URL + '/auth/login';
});
safeOnclick('back-to-servers', () => {
    showPage('servers');
    if (ws) ws.close(); ws = null;
});
safeOnclick('btn-play-submit', handlePlay);
safeOnclick('btn-pause', () => sendControl('toggle'));
safeOnclick('btn-skip', () => sendControl('skip'));
safeOnclick('btn-stop', () => sendControl('stop'));
safeOnclick('btn-leave', () => sendControl('leave'));
safeOnclick('clear-queue', () => sendControl('stop'));
safeOnclick('btn-lyrics', () => alert("🛰️ LYRICS PROTOCOL: Signal decoding in progress. Feature coming in next update."));

const volumeRange = document.getElementById('volume-range');
if (volumeRange) {
    volumeRange.onmousedown = () => { isDraggingVolume = true; };
    volumeRange.onmouseup = () => { isDraggingVolume = false; };
    volumeRange.ontouchstart = () => { isDraggingVolume = true; };
    volumeRange.ontouchend = () => { isDraggingVolume = false; };

    volumeRange.oninput = (e) => {
        const val = e.target.value;
        document.getElementById('volume-val').textContent = `${val}%`;
        sendControl('volume', { level: parseInt(val) });
    };
}

const bbToggle = document.getElementById('bass-boost-toggle');
if (bbToggle) bbToggle.onchange = (e) => sendControl('bass_boost', { enabled: e.target.checked });

const apToggle = document.getElementById('autoplay-toggle');
if (apToggle) apToggle.onchange = (e) => sendControl('auto_play', { enabled: e.target.checked });

// EQ Band Listeners
const debouncedEQ = debounce((band, gain) => {
    sendControl('equalizer', { band, gain });
}, 500);

document.querySelectorAll('.eq-band').forEach(slider => {
    slider.oninput = (e) => {
        const band = e.target.id.replace('eq-', '');
        const gain = parseInt(e.target.value);
        debouncedEQ(band, gain);
    };
});

const playInput = document.getElementById('play-input');
if (playInput) playInput.onkeypress = (e) => { if (e.key === 'Enter') handlePlay(); };

// Bot Management
function addSystemLog(msg, type = '') {
    const log = document.getElementById('system-messages');
    if (!log) return;
    const div = document.createElement('div');
    div.className = `log-entry ${type}`;
    div.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
}

startBotStatusPolling();

async function startBotStatusPolling() {
    if (botStatusInterval) clearInterval(botStatusInterval);
    updateBotStatus();
    botStatusInterval = setInterval(updateBotStatus, 5000);
}

let lastBotState = "unknown"; // "online", "starting", "offline"

async function updateBotStatus() {
    try {
        const status = await fetchAPI('/api/bot/status');
        const light = document.getElementById('bot-status-light');
        const text = document.getElementById('bot-status-text');

        if (!light || !text) return;

        let currentState = "offline";

        if (status.is_running) {
            if (status.bot_ready) {
                light.className = 'status-light online';
                text.className = 'neon-text-green';
                text.textContent = 'ONLINE';
                currentState = "online";
            } else {
                light.className = 'status-light starting';
                text.className = 'neon-text-blue';
                text.textContent = 'INITIALIZING...';
                currentState = "starting";
            }
        } else {
            light.className = 'status-light off';
            text.className = 'neon-text-red';
            text.textContent = 'OFFLINE';
            currentState = "offline";
        }

        // Smart Logging: Log only on state changes
        if (lastBotState !== "unknown" && lastBotState !== currentState) {
            if (currentState === "online") addSystemLog("Systems recovered. Bot is operational.", "success");
            if (currentState === "offline") addSystemLog("Heartbeat lost. Watchdog searching...", "error");
            if (currentState === "starting") addSystemLog("Core process detected. Initializing...", "info");
        }
        lastBotState = currentState;

    } catch (err) {
        console.error("Bot status polling error", err);
        const light = document.getElementById('bot-status-light');
        const text = document.getElementById('bot-status-text');
        if (light && text) {
            light.className = 'status-light off';
            text.className = 'neon-text-red';
            text.textContent = 'CONNECTION LOST';
        }
    }
}

safeOnclick('btn-bot-start', async () => {
    // Legacy start button (hidden)
    addSystemLog("Manual start signal sent.");
});

safeOnclick('btn-bot-stop', async () => {
    if (!confirm("Are you sure you want to FORCE RESTART the system?")) return;

    const btn = document.getElementById('btn-bot-stop');
    const originalText = btn.innerHTML;

    addSystemLog("Sending restart signal...");
    try {
        await fetchAPI('/api/bot/stop', 'POST');
        addSystemLog("Kill signal acknowledged. Waiting for Watchdog...", "success");
        updateBotStatus();

        // Restart Timer / Cooldown
        btn.disabled = true;
        let countdown = 15;
        btn.innerHTML = `<i class="fas fa-sync fa-spin"></i> REBOOTING (${countdown}s)`;

        const timer = setInterval(() => {
            countdown--;
            btn.innerHTML = `<i class="fas fa-sync fa-spin"></i> REBOOTING (${countdown}s)`;
            if (countdown <= 0) {
                clearInterval(timer);
                btn.innerHTML = originalText;
                btn.disabled = false;
                addSystemLog("Reboot cycle complete. Checking status...");
                updateBotStatus();
            }
        }, 1000);

    } catch (err) {
        addSystemLog(`Shutdown error: ${err.message}`, "error");
    }
});

function logout() { localStorage.removeItem('discord_token'); window.location.reload(); }

// Waveform Visualization Engine
function setupWaveform() {
    if (!canvas) return;
    canvas.width = 300;
    canvas.height = 300;
    waveformArr = [];
    for (let i = 0; i < 40; i++) { // Increase density
        waveformArr.push({
            angle: (i / 40) * Math.PI * 2,
            length: 15 + Math.random() * 25,
            phase: Math.random() * Math.PI * 2
        });
    }
    animateWaveform();
}

function animateWaveform() {
    if (!ctx) return;
    ctx.clearRect(0, 0, 300, 300);
    const isPlaying = !isPaused && document.querySelector('.player-card-neon').classList.contains('visualizing');
    const time = Date.now() / 1000;

    ctx.lineCap = 'round';

    waveformArr.forEach((p, i) => {
        const pulse = isPlaying ? Math.sin(time * 5 + p.phase) * 15 + Math.sin(time * 2) * 5 : 0;
        const currentLen = p.length + pulse;

        // Dynamic color based on intensity
        const intensity = isPlaying ? (Math.sin(time * 5 + p.phase) + 1) / 2 : 0;
        ctx.strokeStyle = isPlaying ? `rgba(0, 242, 255, ${0.4 + intensity * 0.6})` : '#222';
        ctx.lineWidth = isPlaying ? 3 + intensity * 2 : 2;

        ctx.beginPath();
        const startX = 150 + Math.cos(p.angle) * 120;
        const startY = 150 + Math.sin(p.angle) * 120;
        const endX = 150 + Math.cos(p.angle) * (120 + currentLen);
        const endY = 150 + Math.sin(p.angle) * (120 + currentLen);

        ctx.moveTo(startX, startY);
        ctx.lineTo(endX, endY);

        if (isPlaying) {
            ctx.shadowBlur = 10 * intensity;
            ctx.shadowColor = '#00f2ff';
        } else {
            ctx.shadowBlur = 0;
        }

        ctx.stroke();
    });

    requestAnimationFrame(animateWaveform);
}

async function fetchAPI(endpoint, method = 'GET') {
    const separator = endpoint.includes('?') ? '&' : '?';
    const res = await fetch(`${API_URL}${endpoint}${separator}token=${currentToken}`, { method });
    if (res.status === 401) logout();

    const data = await res.json();
    if (!res.ok) {
        throw new Error(data.detail || data.error || "Request failed");
    }
    return data;
}

function copyRole(btn) {
    const roleName = "⚛ | 𝐃𝐉𝐌𝐀𝐒𝐓𝐄𝐑";
    navigator.clipboard.writeText(roleName).then(() => {
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<i class="fas fa-check"></i> COPIED!';
        btn.classList.add('btn-success');
        setTimeout(() => {
            btn.innerHTML = originalHtml;
            btn.classList.remove('btn-success');
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy: ', err);
        btn.innerHTML = '<i class="fas fa-times"></i> ERROR';
        setTimeout(() => btn.innerHTML = '<i class="fas fa-copy"></i> ⚛ | 𝐃𝐉𝐌𝐀𝐒𝐓𝐄𝐑', 2000);
    });
}
