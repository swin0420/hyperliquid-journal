// State
let roundTrips = [];
let filteredTrades = [];
let assets = [];
let fundingEvents = [];
let openPositions = [];
let currentTradeId = null;
let positionRefreshInterval = null;

// Filters
let marketFilter = '';
let assetFilter = '';
let pnlFilter = '';
let dateFrom = '';
let dateTo = '';
let sortFilter = 'recent';

// DOM Elements
const walletInput = document.getElementById('wallet-input');
const syncBtn = document.getElementById('sync-btn');
const syncStatus = document.getElementById('sync-status');
const tradesList = document.getElementById('trades-list');
const totalTradesEl = document.getElementById('total-trades');
const totalPnlEl = document.getElementById('total-pnl');
const totalFundingEl = document.getElementById('total-funding');
const totalFeesEl = document.getElementById('total-fees');
const winRateEl = document.getElementById('win-rate');
const bestStreakEl = document.getElementById('best-streak');

// Chart
let pnlChart = null;

// Comparison elements
const thisMonthTradesEl = document.getElementById('this-month-trades');
const thisMonthPnlEl = document.getElementById('this-month-pnl');
const thisMonthWinrateEl = document.getElementById('this-month-winrate');
const lastMonthTradesEl = document.getElementById('last-month-trades');
const lastMonthPnlEl = document.getElementById('last-month-pnl');
const lastMonthWinrateEl = document.getElementById('last-month-winrate');
const changeTradesEl = document.getElementById('change-trades');
const changePnlEl = document.getElementById('change-pnl');
const changeWinrateEl = document.getElementById('change-winrate');

const notesModal = document.getElementById('notes-modal');
const notesTextarea = document.getElementById('notes-textarea');
const closeModalBtn = document.getElementById('close-modal');
const saveNotesBtn = document.getElementById('save-notes-btn');
const marketFilterEl = document.getElementById('market-filter');
const assetFilterEl = document.getElementById('asset-filter');
const pnlFilterEl = document.getElementById('pnl-filter');
const dateFromEl = document.getElementById('date-from');
const dateToEl = document.getElementById('date-to');
const sortFilterEl = document.getElementById('sort-filter');

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
    await loadConfig();
    setupEventListeners();
    await autoSync();
});

function setupEventListeners() {
    syncBtn.addEventListener('click', syncTrades);
    closeModalBtn.addEventListener('click', closeModal);
    saveNotesBtn.addEventListener('click', saveNotes);
    notesModal.addEventListener('click', (e) => {
        if (e.target === notesModal) closeModal();
    });

    // Quick period buttons
    document.querySelectorAll('.quick-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const period = e.target.dataset.period;
            setQuickPeriod(period);
            // Update active state
            document.querySelectorAll('.quick-btn').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
        });
    });

    // Filter listeners
    marketFilterEl.addEventListener('change', (e) => {
        marketFilter = e.target.value;
        populateAssetFilter();
        applyFilters();
    });
    assetFilterEl.addEventListener('change', (e) => {
        assetFilter = e.target.value;
        applyFilters();
    });
    pnlFilterEl.addEventListener('change', (e) => {
        pnlFilter = e.target.value;
        applyFilters();
    });
    dateFromEl.addEventListener('change', (e) => {
        dateFrom = e.target.value;
        quickPeriod = ''; // Clear quick period when using date picker
        document.querySelectorAll('.quick-btn').forEach(b => b.classList.remove('active'));
        applyFilters();
    });
    dateToEl.addEventListener('change', (e) => {
        dateTo = e.target.value;
        quickPeriod = ''; // Clear quick period when using date picker
        document.querySelectorAll('.quick-btn').forEach(b => b.classList.remove('active'));
        applyFilters();
    });
    sortFilterEl.addEventListener('change', (e) => {
        sortFilter = e.target.value;
        applyFilters();
    });
}

async function loadConfig() {
    // Load wallet from localStorage if previously used
    const savedWallet = localStorage.getItem('hl_wallet_address');
    if (savedWallet) {
        walletInput.value = savedWallet;
    }
}

async function autoSync() {
    const wallet = walletInput.value.trim();
    if (wallet) {
        showStatus('Auto-syncing trades...', '');
        await syncTrades();
        await loadPositions();
        startPositionRefresh();
    } else {
        // Just load existing trades if no wallet configured
        await loadRoundTrips();
        await loadFunding();
    }
}

async function loadRoundTrips() {
    const wallet = walletInput.value.trim();
    if (!wallet) {
        roundTrips = [];
        assets = [];
        populateAssetFilter();
        applyFilters();
        return;
    }

    try {
        const [rtRes, assetsRes] = await Promise.all([
            fetch(`/api/roundtrips?wallet=${encodeURIComponent(wallet)}`),
            fetch(`/api/assets?wallet=${encodeURIComponent(wallet)}`)
        ]);
        roundTrips = await rtRes.json();
        assets = await assetsRes.json();

        populateAssetFilter();
        applyFilters();
        updateComparison();
    } catch (e) {
        console.error('Failed to load round trips:', e);
    }
}

async function loadFunding() {
    const wallet = walletInput.value.trim();
    if (!wallet) return;

    try {
        const res = await fetch(`/api/funding?wallet=${wallet}`);
        if (res.ok) {
            fundingEvents = await res.json();
        }
    } catch (e) {
        console.error('Failed to load funding:', e);
    }
}

async function loadPositions() {
    const wallet = walletInput.value.trim();
    if (!wallet) return;

    try {
        const res = await fetch(`/api/positions?wallet=${wallet}`);
        if (res.ok) {
            openPositions = await res.json();
            renderPositions();
        }
    } catch (e) {
        console.error('Failed to load positions:', e);
    }
}

function renderPositions() {
    const container = document.getElementById('positions-list');
    if (!container) return;

    if (openPositions.length === 0) {
        container.innerHTML = '<p class="empty-state">No open positions</p>';
        return;
    }

    container.innerHTML = openPositions.map(pos => {
        const pnlClass = pos.unrealized_pnl >= 0 ? 'positive' : 'negative';
        const pnlDisplay = pos.unrealized_pnl >= 0
            ? `+$${pos.unrealized_pnl.toFixed(2)}`
            : `-$${Math.abs(pos.unrealized_pnl).toFixed(2)}`;

        // Use API's position_value (current market value) and calculate P&L percentage
        const entryValue = pos.entry_price * pos.size;
        const pnlPercent = entryValue > 0 ? ((pos.unrealized_pnl / entryValue) * 100).toFixed(2) : '0.00';
        const pnlPercentDisplay = pos.unrealized_pnl >= 0 ? `+${pnlPercent}%` : `${pnlPercent}%`;

        return `
            <div class="position-card ${pos.direction}">
                <div class="position-info">
                    <span class="position-asset">${pos.asset}</span>
                    <span class="position-direction ${pos.direction}">${pos.direction}</span>
                </div>
                <div class="position-details">
                    <div class="position-detail">
                        <span class="label">Size</span>
                        <span class="value">${pos.size}</span>
                    </div>
                    <div class="position-detail">
                        <span class="label">Position Value</span>
                        <span class="value">$${formatNumber(pos.position_value)}</span>
                    </div>
                    <div class="position-detail">
                        <span class="label">Entry</span>
                        <span class="value">$${formatNumber(pos.entry_price)}</span>
                    </div>
                    <div class="position-detail">
                        <span class="label">Leverage</span>
                        <span class="value">${pos.leverage}x</span>
                    </div>
                    <div class="position-detail">
                        <span class="label">Unrealized P&L</span>
                        <span class="value ${pnlClass}">${pnlDisplay} (${pnlPercentDisplay})</span>
                    </div>
                    ${pos.liquidation_price ? `
                    <div class="position-detail">
                        <span class="label">Liq. Price</span>
                        <span class="value">$${formatNumber(pos.liquidation_price)}</span>
                    </div>` : ''}
                    <div class="position-detail">
                        <span class="label">TP / SL</span>
                        <span class="value"><span class="positive">${pos.take_profit ? '$' + formatNumber(pos.take_profit) : '-'}</span> / <span class="negative">${pos.stop_loss ? '$' + formatNumber(pos.stop_loss) : '-'}</span></span>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function startPositionRefresh() {
    // Refresh positions every 10 seconds
    if (positionRefreshInterval) clearInterval(positionRefreshInterval);
    positionRefreshInterval = setInterval(loadPositions, 10000);
}

function stopPositionRefresh() {
    if (positionRefreshInterval) {
        clearInterval(positionRefreshInterval);
        positionRefreshInterval = null;
    }
}

// Quick period filter - stores the period type, calculates fresh each time
let quickPeriod = ''; // '24h', '7d', '30d', or '' for all

function setQuickPeriod(period) {
    // Clear date inputs when using quick period
    dateFrom = '';
    dateTo = '';
    dateFromEl.value = '';
    dateToEl.value = '';

    quickPeriod = period === 'all' ? '' : period;

    applyFilters();
}

function getQuickPeriodTimestamp() {
    // Calculate the start timestamp for the quick period
    // Rolling time from current moment
    if (!quickPeriod) return 0;

    const now = Date.now();

    if (quickPeriod === '24h') {
        return now - (24 * 60 * 60 * 1000);
    } else if (quickPeriod === '7d') {
        return now - (7 * 24 * 60 * 60 * 1000);
    } else if (quickPeriod === '30d') {
        return now - (30 * 24 * 60 * 60 * 1000);
    }

    return 0;
}

function populateAssetFilter() {
    // Keep current selection
    const current = assetFilterEl.value;

    // Filter assets based on market filter
    let filteredAssets = assets;
    if (marketFilter === 'perp') {
        filteredAssets = assets.filter(a => !a.id.startsWith('@'));
    } else if (marketFilter === 'spot') {
        filteredAssets = assets.filter(a => a.id.startsWith('@'));
    }

    // Clear and repopulate
    assetFilterEl.innerHTML = '<option value="">All Assets</option>';
    filteredAssets.forEach(asset => {
        const option = document.createElement('option');
        option.value = asset.id;
        option.textContent = asset.name;
        assetFilterEl.appendChild(option);
    });

    // Restore selection if still valid
    const validIds = filteredAssets.map(a => a.id);
    if (validIds.includes(current)) {
        assetFilterEl.value = current;
    } else {
        assetFilter = '';
    }
}

function applyFilters() {
    // Determine time filter bounds - calculated fresh each time
    let fromTimestamp = 0;
    let toTimestamp = Infinity;

    if (quickPeriod) {
        // Quick period: calculate from current time (fresh each filter)
        fromTimestamp = getQuickPeriodTimestamp();
        toTimestamp = Date.now();
    } else if (dateFrom || dateTo) {
        // Date picker: use date boundaries
        fromTimestamp = dateFrom ? new Date(dateFrom).setHours(0, 0, 0, 0) : 0;
        toTimestamp = dateTo ? new Date(dateTo).setHours(23, 59, 59, 999) : Infinity;
    }

    filteredTrades = roundTrips.filter(trade => {
        // Time range filter (based on exit time)
        if (fromTimestamp && trade.exit_time < fromTimestamp) {
            return false;
        }
        if (toTimestamp !== Infinity && trade.exit_time > toTimestamp) {
            return false;
        }
        // Market filter
        if (marketFilter && trade.market_type !== marketFilter) {
            return false;
        }
        // Asset filter
        if (assetFilter && trade.asset !== assetFilter) {
            return false;
        }
        // P&L filter (use net P&L: pnl - fees + funding)
        const tradeFunding = getTradeFunding(trade);
        const netPnl = trade.pnl - trade.fees + tradeFunding;
        if (pnlFilter === 'winners' && netPnl <= 0) {
            return false;
        }
        if (pnlFilter === 'losers' && netPnl >= 0) {
            return false;
        }
        return true;
    });

    // Apply sorting (use net P&L including funding for sorting)
    if (sortFilter === 'pnl_high') {
        filteredTrades.sort((a, b) => {
            const netA = a.pnl - a.fees + getTradeFunding(a);
            const netB = b.pnl - b.fees + getTradeFunding(b);
            return netB - netA;
        });
    } else if (sortFilter === 'pnl_low') {
        filteredTrades.sort((a, b) => {
            const netA = a.pnl - a.fees + getTradeFunding(a);
            const netB = b.pnl - b.fees + getTradeFunding(b);
            return netA - netB;
        });
    } else {
        // Default: most recent (by exit_time)
        filteredTrades.sort((a, b) => b.exit_time - a.exit_time);
    }

    renderTrades();
    updateStats();
}

async function syncTrades() {
    const wallet = walletInput.value.trim();
    if (!wallet) {
        showStatus('Please enter a wallet address', 'error');
        return;
    }

    // Save wallet to localStorage for convenience
    localStorage.setItem('hl_wallet_address', wallet);

    syncBtn.disabled = true;
    showStatus('Syncing trades and funding...', '');

    try {
        // Sync trades and funding in parallel
        const [tradesRes] = await Promise.all([
            fetch('/api/trades/sync', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ wallet_address: wallet })
            }),
            loadFunding()
        ]);

        const data = await tradesRes.json();

        if (!tradesRes.ok) {
            throw new Error(data.error || 'Sync failed');
        }

        showStatus(`Synced ${data.total_trades} fills`, 'success');
        await loadRoundTrips();
        await loadPositions();
        startPositionRefresh();
    } catch (e) {
        showStatus(`Error: ${e.message}`, 'error');
    } finally {
        syncBtn.disabled = false;
    }
}

function showStatus(message, type) {
    syncStatus.textContent = message;
    syncStatus.className = 'status ' + type;
}

function renderTrades() {
    if (filteredTrades.length === 0) {
        if (roundTrips.length === 0) {
            tradesList.innerHTML = '<p class="empty-state">No trades yet. Enter your wallet address and click Sync.</p>';
        } else {
            tradesList.innerHTML = '<p class="empty-state">No trades match the current filters.</p>';
        }
        return;
    }

    tradesList.innerHTML = filteredTrades.map(trade => createTradeCard(trade)).join('');
}

function formatDuration(ms) {
    if (ms < 0) ms = 0;

    const seconds = Math.floor(ms / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (days > 0) {
        const remainingHours = hours % 24;
        return remainingHours > 0 ? `${days}d ${remainingHours}h` : `${days}d`;
    }
    if (hours > 0) {
        const remainingMinutes = minutes % 60;
        return remainingMinutes > 0 ? `${hours}h ${remainingMinutes}m` : `${hours}h`;
    }
    if (minutes > 0) {
        return `${minutes}m`;
    }
    return `${seconds}s`;
}

function createTradeCard(trade) {
    const exitDate = new Date(trade.exit_time);
    const formattedDate = exitDate.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric'
    });

    // Calculate funding during trade hold period
    const tradeFunding = getTradeFunding(trade);

    // Calculate net P&L (after fees + funding)
    // Funding can be positive (received) or negative (paid)
    const netPnl = trade.pnl - trade.fees + tradeFunding;
    const pnlClass = netPnl > 0 ? 'positive' : netPnl < 0 ? 'negative' : '';
    const pnlDisplay = netPnl >= 0 ? `+$${netPnl.toFixed(2)}` : `-$${Math.abs(netPnl).toFixed(2)}`;

    // Calculate percentage return based on net P&L
    const entryValue = trade.entry_price * trade.size;
    const pnlPercent = entryValue > 0 ? ((netPnl / entryValue) * 100).toFixed(2) : '0.00';
    const pnlPercentDisplay = netPnl >= 0 ? `+${pnlPercent}%` : `${pnlPercent}%`;

    // Format duration
    const duration = formatDuration(trade.duration_ms || 0);

    const notesPreview = trade.notes ? `"${trade.notes.substring(0, 50)}${trade.notes.length > 50 ? '...' : ''}"` : '';
    const hasNotes = trade.notes && trade.notes.trim().length > 0;

    // Use display_name if available, otherwise asset
    const displayName = trade.display_name || trade.asset;

    // Market type badge for spot
    const marketBadge = trade.market_type === 'spot' ? '<span class="market-badge spot">SPOT</span>' : '';

    return `
        <div class="trade-card ${trade.direction}" onmouseenter="expandTradeCard(this)" onmouseleave="collapseTradeCard(this)">
            <div class="trade-summary">
                <span class="trade-asset">${displayName} ${marketBadge}</span>
                <span class="trade-direction ${trade.direction}">${trade.direction}</span>
                <span class="trade-pnl ${pnlClass}">${pnlDisplay}</span>
                <span class="trade-date">${formattedDate}</span>
                <span class="expand-icon">▼</span>
            </div>
            <div class="trade-details" hidden>
                <div class="trade-details-grid">
                    <div class="trade-detail">
                        <span class="detail-label">Entry</span>
                        <span class="detail-value">$${formatNumber(trade.entry_price)}</span>
                    </div>
                    <div class="trade-detail">
                        <span class="detail-label">Exit</span>
                        <span class="detail-value">$${formatNumber(trade.exit_price)}</span>
                    </div>
                    <div class="trade-detail">
                        <span class="detail-label">Size</span>
                        <span class="detail-value">${formatNumber(trade.size)}</span>
                    </div>
                    <div class="trade-detail">
                        <span class="detail-label">Net P&L</span>
                        <span class="detail-value ${pnlClass}">${pnlDisplay} (${pnlPercentDisplay})</span>
                    </div>
                    <div class="trade-detail">
                        <span class="detail-label">Held</span>
                        <span class="detail-value">${duration}</span>
                    </div>
                    <div class="trade-detail">
                        <span class="detail-label">Fees</span>
                        <span class="detail-value">-$${trade.fees.toFixed(2)}</span>
                    </div>
                    ${trade.market_type === 'perp' ? `<div class="trade-detail">
                        <span class="detail-label">Funding</span>
                        <span class="detail-value ${tradeFunding >= 0 ? 'positive' : 'negative'}">${tradeFunding >= 0 ? '+' : ''}$${tradeFunding.toFixed(2)}</span>
                    </div>` : ''}
                </div>
                ${notesPreview ? `<div class="trade-notes-preview">${notesPreview}</div>` : ''}
                <button class="notes-btn ${hasNotes ? 'has-notes' : ''}" onclick="openNotesModal('${trade.id}')">
                    ${hasNotes ? 'Edit Notes' : 'Add Notes'}
                </button>
            </div>
        </div>
    `;
}

function formatNumber(num) {
    if (num >= 1000) {
        return num.toLocaleString('en-US', { maximumFractionDigits: 2 });
    }
    if (num < 0.01) {
        return num.toPrecision(4);
    }
    return num.toFixed(num < 1 ? 4 : 2);
}

function getFilteredFunding() {
    // Determine time filter bounds - calculated fresh each time
    let fromTimestamp = 0;
    let toTimestamp = Infinity;

    if (quickPeriod) {
        // Quick period: calculate from current time (fresh each filter)
        fromTimestamp = getQuickPeriodTimestamp();
        toTimestamp = Date.now();
    } else if (dateFrom || dateTo) {
        // Date picker: use date boundaries
        fromTimestamp = dateFrom ? new Date(dateFrom).setHours(0, 0, 0, 0) : 0;
        toTimestamp = dateTo ? new Date(dateTo).setHours(23, 59, 59, 999) : Infinity;
    }

    return fundingEvents.filter(event => {
        // Time range filter
        if (fromTimestamp && event.timestamp < fromTimestamp) {
            return false;
        }
        if (toTimestamp !== Infinity && event.timestamp > toTimestamp) {
            return false;
        }
        // Market filter (spot has no funding)
        if (marketFilter === 'spot') {
            return false;
        }
        // Asset filter
        if (assetFilter && event.coin !== assetFilter) {
            return false;
        }
        return true;
    });
}

function getTradeFunding(trade) {
    // Get funding that occurred during this trade's hold period
    // Funding only applies to perps, not spot
    if (trade.market_type === 'spot') return 0;

    return fundingEvents.filter(event => {
        // Match asset
        if (event.coin !== trade.asset) return false;
        // Check if funding occurred during trade hold period
        return event.timestamp >= trade.entry_time && event.timestamp <= trade.exit_time;
    }).reduce((sum, e) => sum + e.usdc, 0);
}

function updateStats() {
    // Use filtered trades for stats
    const trades = filteredTrades;

    // Total trades
    totalTradesEl.textContent = trades.length;

    // Calculate totals
    const totalGrossPnl = trades.reduce((sum, t) => sum + (t.pnl || 0), 0);
    const totalFees = trades.reduce((sum, t) => sum + (t.fees || 0), 0);

    // Get all funding in the time period (matching Hyperliquid's calculation)
    const filteredFunding = getFilteredFunding();
    const totalFunding = filteredFunding.reduce((sum, e) => sum + e.usdc, 0);

    // Net P&L = Gross P&L - Fees + Funding (same as Hyperliquid)
    const totalNetPnl = totalGrossPnl - totalFees + totalFunding;

    // Net P&L (after fees + funding)
    totalPnlEl.textContent = `${totalNetPnl >= 0 ? '+' : ''}$${totalNetPnl.toFixed(2)}`;
    totalPnlEl.className = 'stat-value ' + (totalNetPnl >= 0 ? 'positive' : 'negative');

    // Funding display
    totalFundingEl.textContent = `${totalFunding >= 0 ? '+' : ''}$${totalFunding.toFixed(2)}`;
    totalFundingEl.className = 'stat-value ' + (totalFunding >= 0 ? 'positive' : 'negative');

    // Total Fees
    totalFeesEl.textContent = `-$${totalFees.toFixed(2)}`;
    totalFeesEl.className = 'stat-value negative';

    // Win rate (based on trade P&L - fees, funding counted separately)
    const wins = trades.filter(t => (t.pnl - t.fees) > 0).length;
    const winRate = trades.length > 0 ? (wins / trades.length * 100) : 0;
    winRateEl.textContent = `${winRate.toFixed(1)}%`;

    // Streaks
    const streaks = calculateStreaks(trades);
    bestStreakEl.textContent = streaks.bestWin > 0 ? `${streaks.bestWin}` : '-';

    // Update chart
    updatePnlChart(trades, totalFunding);
}

function calculateStreaks(trades) {
    if (trades.length === 0) {
        return { current: { count: 0, type: '' }, bestWin: 0, bestLoss: 0 };
    }

    // Sort by exit time (oldest first for streak calculation)
    const sorted = [...trades].sort((a, b) => a.exit_time - b.exit_time);

    let currentStreak = 0;
    let currentType = '';
    let bestWinStreak = 0;
    let bestLossStreak = 0;
    let tempStreak = 0;
    let tempType = '';

    for (const trade of sorted) {
        const isWin = (trade.pnl - trade.fees) > 0;
        const type = isWin ? 'W' : 'L';

        if (type === tempType) {
            tempStreak++;
        } else {
            // Streak broken, update bests
            if (tempType === 'W' && tempStreak > bestWinStreak) {
                bestWinStreak = tempStreak;
            } else if (tempType === 'L' && tempStreak > bestLossStreak) {
                bestLossStreak = tempStreak;
            }
            tempStreak = 1;
            tempType = type;
        }
    }

    // Final streak
    if (tempType === 'W' && tempStreak > bestWinStreak) {
        bestWinStreak = tempStreak;
    } else if (tempType === 'L' && tempStreak > bestLossStreak) {
        bestLossStreak = tempStreak;
    }

    return {
        current: { count: tempStreak, type: tempType },
        bestWin: bestWinStreak,
        bestLoss: bestLossStreak
    };
}

function updatePnlChart(trades, totalFunding) {
    const ctx = document.getElementById('pnl-chart');
    if (!ctx) return;

    // Sort by exit time (oldest first)
    const sorted = [...trades].sort((a, b) => a.exit_time - b.exit_time);

    // Build cumulative P&L data
    let cumulative = 0;
    const labels = [];
    const data = [];
    const tradeDetails = []; // Store details for tooltip

    for (const trade of sorted) {
        const tradePnl = trade.pnl - trade.fees;
        cumulative += tradePnl;

        const date = new Date(trade.exit_time);
        labels.push(date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }));
        data.push(cumulative);
        tradeDetails.push({
            asset: trade.display_name || trade.asset,
            tradePnl: tradePnl,
            direction: trade.direction,
            date: date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
        });
    }

    // Add funding as final point to show Net P&L (matches stats)
    const filteredFundingTotal = getFilteredFunding().reduce((sum, e) => sum + e.usdc, 0);
    if (sorted.length > 0) {
        cumulative += filteredFundingTotal;
        labels.push('');
        data.push(cumulative);
        tradeDetails.push({
            asset: 'Net P&L (incl. Funding)',
            tradePnl: filteredFundingTotal,
            direction: '',
            date: `Funding: $${filteredFundingTotal.toFixed(2)}`
        });
    }

    // Destroy existing chart
    if (pnlChart) {
        pnlChart.destroy();
    }

    // Create new chart
    pnlChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Cumulative P&L',
                data: data,
                borderColor: cumulative >= 0 ? '#22c55e' : '#ef4444',
                backgroundColor: cumulative >= 0 ? 'rgba(34, 197, 94, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                fill: true,
                tension: 0.1,
                pointRadius: 3,
                pointHoverRadius: 5
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    callbacks: {
                        title: (context) => {
                            const idx = context[0].dataIndex;
                            const detail = tradeDetails[idx];
                            if (detail && detail.asset !== 'Funding') {
                                return `${detail.asset} (${detail.direction})`;
                            }
                            return detail ? detail.asset : '';
                        },
                        label: (context) => {
                            const idx = context.dataIndex;
                            const detail = tradeDetails[idx];
                            const lines = [`Cumulative: $${context.raw.toFixed(2)}`];
                            if (detail) {
                                const pnlStr = detail.tradePnl >= 0 ? `+$${detail.tradePnl.toFixed(2)}` : `-$${Math.abs(detail.tradePnl).toFixed(2)}`;
                                lines.push(`P&L: ${pnlStr}`);
                                if (detail.date) {
                                    lines.push(`${detail.date}`);
                                }
                            }
                            return lines;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: {
                        color: 'rgba(255, 255, 255, 0.1)'
                    },
                    ticks: {
                        color: '#888',
                        maxTicksLimit: 10
                    }
                },
                y: {
                    grid: {
                        color: 'rgba(255, 255, 255, 0.1)'
                    },
                    ticks: {
                        color: '#888',
                        callback: (value) => `$${value.toFixed(2)}`,
                        maxTicksLimit: 6
                    }
                }
            }
        }
    });
}

function updateComparison() {
    const now = new Date();

    // This month: start of current month to now
    const thisMonthStart = new Date(now.getFullYear(), now.getMonth(), 1).getTime();
    const thisMonthEnd = now.getTime();

    // Last month: start to end of previous month
    const lastMonthStart = new Date(now.getFullYear(), now.getMonth() - 1, 1).getTime();
    const lastMonthEnd = new Date(now.getFullYear(), now.getMonth(), 0, 23, 59, 59, 999).getTime();

    // Filter trades for each period (use all roundTrips, ignoring current filters)
    const thisMonthTrades = roundTrips.filter(t =>
        t.exit_time >= thisMonthStart && t.exit_time <= thisMonthEnd
    );
    const lastMonthTrades = roundTrips.filter(t =>
        t.exit_time >= lastMonthStart && t.exit_time <= lastMonthEnd
    );

    // Calculate stats for this month
    const thisMonthStats = calculatePeriodStats(thisMonthTrades, thisMonthStart, thisMonthEnd);
    const lastMonthStats = calculatePeriodStats(lastMonthTrades, lastMonthStart, lastMonthEnd);

    // Update this month
    thisMonthTradesEl.textContent = thisMonthStats.trades;
    thisMonthPnlEl.textContent = `${thisMonthStats.pnl >= 0 ? '+' : ''}$${thisMonthStats.pnl.toFixed(2)}`;
    thisMonthPnlEl.className = 'comp-value ' + (thisMonthStats.pnl >= 0 ? 'positive' : 'negative');
    thisMonthWinrateEl.textContent = `${thisMonthStats.winRate.toFixed(1)}%`;

    // Update last month
    lastMonthTradesEl.textContent = lastMonthStats.trades;
    lastMonthPnlEl.textContent = `${lastMonthStats.pnl >= 0 ? '+' : ''}$${lastMonthStats.pnl.toFixed(2)}`;
    lastMonthPnlEl.className = 'comp-value ' + (lastMonthStats.pnl >= 0 ? 'positive' : 'negative');
    lastMonthWinrateEl.textContent = `${lastMonthStats.winRate.toFixed(1)}%`;

    // Calculate and update changes
    const tradesDiff = thisMonthStats.trades - lastMonthStats.trades;
    const winRateDiff = thisMonthStats.winRate - lastMonthStats.winRate;

    // Calculate P&L percentage change
    let pnlPercentChange = 0;
    if (lastMonthStats.pnl !== 0) {
        pnlPercentChange = ((thisMonthStats.pnl - lastMonthStats.pnl) / Math.abs(lastMonthStats.pnl)) * 100;
    } else if (thisMonthStats.pnl !== 0) {
        pnlPercentChange = thisMonthStats.pnl > 0 ? 100 : -100;
    }

    changeTradesEl.textContent = `${tradesDiff >= 0 ? '+' : ''}${tradesDiff}`;
    changeTradesEl.className = 'comp-value ' + (tradesDiff >= 0 ? 'positive' : 'negative');

    changePnlEl.textContent = `${pnlPercentChange >= 0 ? '+' : ''}${pnlPercentChange.toFixed(1)}%`;
    changePnlEl.className = 'comp-value ' + (pnlPercentChange >= 0 ? 'positive' : 'negative');

    changeWinrateEl.textContent = `${winRateDiff >= 0 ? '+' : ''}${winRateDiff.toFixed(1)}%`;
    changeWinrateEl.className = 'comp-value ' + (winRateDiff >= 0 ? 'positive' : 'negative');
}

function calculatePeriodStats(trades, startTime, endTime) {
    const grossPnl = trades.reduce((sum, t) => sum + (t.pnl || 0), 0);
    const fees = trades.reduce((sum, t) => sum + (t.fees || 0), 0);

    // Get funding for the period
    const periodFunding = fundingEvents.filter(e =>
        e.timestamp >= startTime && e.timestamp <= endTime
    ).reduce((sum, e) => sum + e.usdc, 0);

    const netPnl = grossPnl - fees + periodFunding;
    const wins = trades.filter(t => (t.pnl - t.fees) > 0).length;
    const winRate = trades.length > 0 ? (wins / trades.length * 100) : 0;

    return {
        trades: trades.length,
        pnl: netPnl,
        winRate: winRate
    };
}

function expandTradeCard(card) {
    const details = card.querySelector('.trade-details');
    details.hidden = false;
    card.classList.add('expanded');
}

function collapseTradeCard(card) {
    const details = card.querySelector('.trade-details');
    details.hidden = true;
    card.classList.remove('expanded');
}

function openNotesModal(tradeId) {
    currentTradeId = tradeId;
    const trade = roundTrips.find(t => t.id === tradeId);
    if (trade) {
        notesTextarea.value = trade.notes || '';
        notesModal.classList.remove('hidden');
        notesTextarea.focus();
    }
}

function closeModal() {
    notesModal.classList.add('hidden');
    currentTradeId = null;
}

async function saveNotes() {
    if (!currentTradeId) return;

    const wallet = walletInput.value.trim();
    if (!wallet) {
        alert('No wallet address provided');
        return;
    }

    const notes = notesTextarea.value.trim();
    saveNotesBtn.disabled = true;

    try {
        const res = await fetch(`/api/trades/${currentTradeId}/notes`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ notes, wallet_address: wallet })
        });

        if (!res.ok) {
            throw new Error('Failed to save notes');
        }

        // Update local state
        const trade = roundTrips.find(t => t.id === currentTradeId);
        if (trade) {
            trade.notes = notes;
        }

        applyFilters();
        closeModal();
    } catch (e) {
        alert('Failed to save notes: ' + e.message);
    } finally {
        saveNotesBtn.disabled = false;
    }
}
