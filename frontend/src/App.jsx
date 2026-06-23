import React, { useState, useEffect } from 'react';
import axios from 'axios';

// Use environment variable or default to local Uvicorn port
let API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
if (API_BASE_URL.endsWith('/')) {
  API_BASE_URL = API_BASE_URL.slice(0, -1);
}

function App() {
  // Transaction Form State
  const [userId, setUserId] = useState('');
  const [amount, setAmount] = useState('');
  const [type, setType] = useState('credit');
  const [requestId, setRequestId] = useState(generateRandomKey());
  const [txnLoading, setTxnLoading] = useState(false);

  // User Summary State
  const [summaryUserId, setSummaryUserId] = useState('');
  const [summaryData, setSummaryData] = useState(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  // Leaderboard State
  const [leaderboard, setLeaderboard] = useState([]);
  const [leaderboardLoading, setLeaderboardLoading] = useState(false);

  // Global Notification State (Toast)
  const [toast, setToast] = useState({ show: false, type: 'success', title: '', message: '' });

  // Generate a random string to act as idempotency key
  function generateRandomKey() {
    return 'req_' + Math.random().toString(36).substring(2, 10) + Math.random().toString(36).substring(2, 6);
  }

  const handleRegenRequestId = () => {
    setRequestId(generateRandomKey());
  };

  const showToast = (type, title, message) => {
    setToast({ show: true, type, title, message });
    // Auto-hide toast after 5 seconds
    setTimeout(() => {
      setToast((prev) => ({ ...prev, show: false }));
    }, 5000);
  };

  // Fetch Leaderboard
  const fetchLeaderboard = async () => {
    setLeaderboardLoading(true);
    try {
      const response = await axios.get(`${API_BASE_URL}/ranking`);
      if (response.data && response.data.success) {
        setLeaderboard(response.data.leaderboard);
      }
    } catch (err) {
      console.error('Error fetching leaderboard:', err);
    } finally {
      setLeaderboardLoading(false);
    }
  };

  // Fetch User Summary
  const fetchUserSummary = async (idToSearch) => {
    const targetId = idToSearch || summaryUserId;
    if (!targetId.trim()) {
      showToast('error', 'Validation Error', 'Please enter a User ID to fetch summary.');
      return;
    }
    setSummaryLoading(true);
    setSummaryData(null);
    try {
      const response = await axios.get(`${API_BASE_URL}/summary/${targetId}`);
      setSummaryData(response.data);
    } catch (err) {
      const errorMsg = err.response?.data?.error || err.response?.data?.detail || 'Failed to fetch user summary.';
      showToast('error', 'Fetch Summary Failed', errorMsg);
    } finally {
      setSummaryLoading(false);
    }
  };

  // Submit Transaction
  const handleSubmitTransaction = async (e) => {
    e.preventDefault();
    if (!userId.trim()) {
      showToast('error', 'Validation Error', 'User ID is required.');
      return;
    }
    if (!amount || parseFloat(amount) <= 0) {
      showToast('error', 'Validation Error', 'Amount must be greater than 0.');
      return;
    }
    if (!requestId.trim()) {
      showToast('error', 'Validation Error', 'Request ID (Idempotency Key) is required.');
      return;
    }

    setTxnLoading(true);
    try {
      const payload = {
        request_id: requestId,
        user_id: userId.trim(),
        amount: parseFloat(amount),
        type: type
      };

      const response = await axios.post(`${API_BASE_URL}/transaction`, payload);
      
      if (response.data && response.data.success) {
        showToast(
          'success', 
          'Transaction Successful', 
          `Txn ID: ${response.data.transaction_id}. New Balance: $${response.data.new_balance}`
        );
        // Refresh leaderboard
        fetchLeaderboard();
        // If the summary is open for this user, refresh it as well
        if (summaryUserId.trim() === userId.trim()) {
          fetchUserSummary(userId.trim());
        }
      }
    } catch (err) {
      const errorMsg = err.response?.data?.error || err.response?.data?.detail || 'Transaction failed.';
      showToast('error', 'Transaction Rejected', errorMsg);
    } finally {
      setTxnLoading(false);
    }
  };

  // Load Leaderboard on mount
  useEffect(() => {
    fetchLeaderboard();
  }, []);

  return (
    <div className="app-container">
      {/* Header */}
      <header className="app-header">
        <div className="app-title-group">
          <h1 className="app-title">Fair Transaction & Ranking System</h1>
          <p className="app-subtitle">Abuse-Protected Ledger with Mathematically Fair Consistency Scoring</p>
        </div>
      </header>

      {/* Toast Alert */}
      {toast.show && (
        <div className={`toast ${toast.type}`}>
          <div className="toast-icon">
            {toast.type === 'success' ? '✓' : '⚠️'}
          </div>
          <div className="toast-content">
            <div className="toast-title">{toast.title}</div>
            <div>{toast.message}</div>
          </div>
          <button 
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', fontWeight: 'bold' }} 
            onClick={() => setToast((prev) => ({ ...prev, show: false }))}
          >
            ×
          </button>
        </div>
      )}

      {/* Grid Dashboard */}
      <div className="dashboard-grid">
        {/* Section 1: Transaction Form Card */}
        <div className="card">
          <h2 className="card-title">
            <span className="card-header-icon">⇄</span> New Transaction
          </h2>
          <form onSubmit={handleSubmitTransaction}>
            <div className="form-group">
              <label className="form-label">User ID</label>
              <div className="input-wrapper">
                <input 
                  type="text" 
                  className="form-input" 
                  value={userId}
                  onChange={(e) => setUserId(e.target.value)}
                  placeholder="e.g. user_101"
                />
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Amount ($)</label>
              <div className="input-wrapper">
                <input 
                  type="number" 
                  step="any"
                  className="form-input" 
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  placeholder="0.00"
                />
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Transaction Type</label>
              <div className="type-selector">
                <label className={`type-option credit ${type === 'credit' ? 'selected' : ''}`}>
                  <input 
                    type="radio" 
                    name="type" 
                    value="credit"
                    checked={type === 'credit'}
                    onChange={() => setType('credit')}
                  />
                  Credit (+)
                </label>
                <label className={`type-option debit ${type === 'debit' ? 'selected' : ''}`}>
                  <input 
                    type="radio" 
                    name="type" 
                    value="debit"
                    checked={type === 'debit'}
                    onChange={() => setType('debit')}
                  />
                  Debit (-)
                </label>
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Request ID (Idempotency Key)</label>
              <div className="input-wrapper">
                <input 
                  type="text" 
                  className="form-input" 
                  style={{ paddingRight: '90px' }}
                  value={requestId}
                  onChange={(e) => setRequestId(e.target.value)}
                  placeholder="Idempotency key"
                />
                <button 
                  type="button" 
                  className="input-action-btn"
                  onClick={handleRegenRequestId}
                >
                  Regen
                </button>
              </div>
              <small style={{ display: 'block', color: 'var(--text-light)', marginTop: '4px', fontSize: '0.75rem' }}>
                Keep it same to test duplicate prevention and trust penalties.
              </small>
            </div>

            <button 
              type="submit" 
              className="btn btn-primary"
              disabled={txnLoading}
            >
              {txnLoading ? <span className="spinner"></span> : 'Submit Transaction'}
            </button>
          </form>
        </div>

        {/* Section 2: User Summary Card */}
        <div className="card">
          <h2 className="card-title">
            <span className="card-header-icon">👤</span> User Summary
          </h2>
          <div className="summary-search-container">
            <input 
              type="text" 
              className="form-input" 
              value={summaryUserId}
              onChange={(e) => setSummaryUserId(e.target.value)}
              placeholder="Enter User ID to fetch summary"
            />
            <button 
              className="btn btn-primary" 
              style={{ width: 'auto', whiteSpace: 'nowrap', padding: '0 1.25rem' }}
              onClick={() => fetchUserSummary()}
              disabled={summaryLoading}
            >
              {summaryLoading ? <span className="spinner"></span> : 'Fetch'}
            </button>
          </div>

          {summaryData ? (
            <div className="summary-stats-grid">
              <div className="stat-box full-width">
                <span className="stat-label">Ranking Score</span>
                <span className="stat-value">{summaryData.ranking_score}</span>
              </div>
              <div className="stat-box">
                <span className="stat-label">Current Balance</span>
                <span className="stat-value">${summaryData.balance}</span>
              </div>
              <div className="stat-box">
                <span className="stat-label">Transactions</span>
                <span className="stat-value">{summaryData.total_transactions}</span>
              </div>
              <div className="stat-box">
                <span className="stat-label">Credits (+)</span>
                <span className="stat-value credit">${summaryData.total_credits}</span>
              </div>
              <div className="stat-box">
                <span className="stat-label">Debits (-)</span>
                <span className="stat-value debit">${summaryData.total_debits}</span>
              </div>
            </div>
          ) : (
            <div className="empty-state">
              <div className="empty-state-icon">🔍</div>
              <div>Search for a User ID to inspect account details and scores.</div>
            </div>
          )}
        </div>

        {/* Section 3: Leaderboard Card */}
        <div className="card leaderboard-card">
          <div className="card-title" style={{ borderBottom: 'none', marginBottom: '1rem' }}>
            <span className="card-header-icon">🏆</span> Leaderboard
            <div className="header-actions">
              <button 
                className="btn-icon" 
                onClick={fetchLeaderboard}
                disabled={leaderboardLoading}
                title="Refresh rankings"
              >
                {leaderboardLoading ? <span className="spinner"></span> : '↻'}
              </button>
            </div>
          </div>
          
          <div className="table-wrapper">
            {leaderboard.length > 0 ? (
              <table className="leaderboard-table">
                <thead>
                  <tr>
                    <th>Rank</th>
                    <th>User ID</th>
                    <th>Balance ($)</th>
                    <th>Ranking Score</th>
                  </tr>
                </thead>
                <tbody>
                  {leaderboard.map((user) => (
                    <tr key={user.user_id}>
                      <td>
                        <span className={`rank-badge ${
                          user.rank === 1 ? 'rank-1' :
                          user.rank === 2 ? 'rank-2' :
                          user.rank === 3 ? 'rank-3' : 'rank-other'
                        }`}>
                          {user.rank}
                        </span>
                      </td>
                      <td style={{ fontWeight: '600' }}>{user.user_id}</td>
                      <td>${user.balance}</td>
                      <td>
                        <span className="ranking-score-pill">{user.ranking_score}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="empty-state">
                <div className="empty-state-icon">👑</div>
                <div>No users ranked yet. Submit a transaction to populate the leaderboard.</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
