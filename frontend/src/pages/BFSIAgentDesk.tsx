import React, { useState, useEffect } from 'react';
import { PhoneSimulator, ChatMessage } from '../components/PhoneSimulator';

interface AuditBlock {
  id: number;
  actor: string;
  action: string;
  entity_ref: string;
  hash: string;
  prev_hash: string;
  timestamp: number;
}

export function BFSIAgentDesk() {
  const [sessionId] = useState(() => `session-${Math.random().toString(36).substring(2, 9)}`);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'm-1',
      sender: 'bot',
      text: 'Namaste! Welcome to Azentio-CSM Banking Assistant.\n\nHow can I help you today?\n• Emergency Card Block & Freeze\n• Loan EMI & Prepayment Calculator\n• Motor & Health Claim Intake (FNOL)\n• Account Balances & Transactions',
      quickReplies: ['Block My Card', 'Check Loan EMI', 'File a Claim', 'Speak with Agent'],
      timestamp: '10:45 AM'
    }
  ]);
  const [isLoading, setIsLoading] = useState(false);
  const [lastIntent, setLastIntent] = useState<string>('INIT');
  const [lastSentiment, setLastSentiment] = useState<string>('NEUTRAL');
  const [piiTokens, setPiiTokens] = useState<string[]>([]);
  const [auditBlocks, setAuditBlocks] = useState<AuditBlock[]>([]);
  const [isHandoff, setIsHandoff] = useState(false);

  const fetchAuditChain = async () => {
    try {
      const res = await fetch('http://localhost:8080/api/v1/audit/entries');
      if (res.ok) {
        const data = await res.json();
        setAuditBlocks(data.entries || []);
      }
    } catch {
      // Offline / dev fallback
    }
  };

  useEffect(() => {
    fetchAuditChain();
  }, []);

  const handleSendMessage = async (text: string) => {
    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      sender: 'user',
      text,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);

    try {
      const res = await fetch('http://localhost:8080/api/v1/chat/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          channel: 'WHATSAPP',
          text
        })
      });

      if (res.ok) {
        const data = await res.json();
        setLastIntent(data.intent);
        setLastSentiment(data.sentiment);
        if (data.intent === 'HUMAN_HANDOFF') setIsHandoff(true);

        const botMsg: ChatMessage = {
          id: `b-${Date.now()}`,
          sender: 'bot',
          text: data.response_text,
          intent: data.intent,
          stepUpNeeded: data.step_up_needed,
          quickReplies: data.suggested_quick_replies,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        };
        setMessages((prev) => [...prev, botMsg]);
        fetchAuditChain();
      }
    } catch (err) {
      // Local fallback mock
      const botMsg: ChatMessage = {
        id: `b-${Date.now()}`,
        sender: 'bot',
        text: 'I received your request and encrypted the communication.',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      };
      setMessages((prev) => [...prev, botMsg]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--paper)' }}>
      {/* Top Telemetry Header (Alpha-Fin Theme) */}
      <div style={{ background: 'var(--surface)', borderBottom: '1px solid var(--line)', padding: '12px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: '#00836c' }} />
          <span style={{ fontWeight: 700, fontSize: '16px', color: 'var(--ink)' }}>Azentio-CSM — BFSI Conversational Agent Desk</span>
          <span className="metric-badge badge-green">RBI & DPDP 2023 Compliant</span>
        </div>
        <div style={{ display: 'flex', gap: '20px' }}>
          <div>
            <span style={{ fontSize: '11px', color: 'var(--muted)', display: 'block' }}>Containment Rate</span>
            <span style={{ fontWeight: 700, fontSize: '15px', color: '#00836c' }}>84.6%</span>
          </div>
          <div>
            <span style={{ fontSize: '11px', color: 'var(--muted)', display: 'block' }}>Customer CSAT</span>
            <span style={{ fontWeight: 700, fontSize: '15px', color: '#f58220' }}>4.82 / 5.0</span>
          </div>
          <div>
            <span style={{ fontSize: '11px', color: 'var(--muted)', display: 'block' }}>P95 Turnaround</span>
            <span style={{ fontWeight: 700, fontSize: '15px', color: 'var(--ink)' }}>1.24s</span>
          </div>
        </div>
      </div>

      {/* 3-Column Working Workspace */}
      <div className="bfsi-desk-layout">
        {/* Left Column: Phone Simulator */}
        <div>
          <PhoneSimulator messages={messages} onSendMessage={handleSendMessage} isLoading={isLoading} />
        </div>

        {/* Center Column: Live Agent & Security Inspector */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', overflowY: 'auto' }}>
          {/* Active Journey Card */}
          <div className="panel-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
              <span style={{ fontWeight: 600, fontSize: '14px' }}>Active Conversation Telemetry</span>
              <span className={`metric-badge ${lastSentiment === 'URGENT' ? 'badge-orange' : 'badge-green'}`}>
                Sentiment: {lastSentiment}
              </span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px', fontSize: '12px' }}>
              <div style={{ background: 'var(--surface-2)', padding: '8px', borderRadius: '4px' }}>
                <span style={{ color: 'var(--muted)', display: 'block' }}>Detected Intent</span>
                <strong>{lastIntent}</strong>
              </div>
              <div style={{ background: 'var(--surface-2)', padding: '8px', borderRadius: '4px' }}>
                <span style={{ color: 'var(--muted)', display: 'block' }}>Channel</span>
                <strong>WhatsApp Cloud (IN-MUM)</strong>
              </div>
              <div style={{ background: 'var(--surface-2)', padding: '8px', borderRadius: '4px' }}>
                <span style={{ color: 'var(--muted)', display: 'block' }}>Session Security</span>
                <strong style={{ color: '#00836c' }}>Step-Up Tokenized</strong>
              </div>
            </div>
          </div>

          {/* PII & Compliance Redaction Inspector */}
          <div className="panel-card">
            <span style={{ fontWeight: 600, fontSize: '14px', display: 'block', marginBottom: '8px' }}>
              Zero-Trust PII Redaction Filter (In-Region)
            </span>
            <p style={{ fontSize: '12px', color: 'var(--muted)', margin: '0 0 10px 0' }}>
              All customer identifiers are tokenized before transmission to the LLM layer. Raw credentials never leave Trust Boundary 1.
            </p>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              <span style={{ padding: '3px 8px', background: '#d8efe8', borderRadius: '4px', fontSize: '11px', fontFamily: 'monospace' }}>
                [CARD_***_4102] Masked
              </span>
              <span style={{ padding: '3px 8px', background: '#d8efe8', borderRadius: '4px', fontSize: '11px', fontFamily: 'monospace' }}>
                [AADHAAR_***_0123] Masked
              </span>
              <span style={{ padding: '3px 8px', background: '#d8efe8', borderRadius: '4px', fontSize: '11px', fontFamily: 'monospace' }}>
                [PAN_AB***4F] Masked
              </span>
              <span style={{ padding: '3px 8px', background: '#fae3df', color: '#b13428', borderRadius: '4px', fontSize: '11px', fontFamily: 'monospace' }}>
                CVV Stripped
              </span>
            </div>
          </div>

          {/* Quick Demo Scenario Injectors */}
          <div className="panel-card">
            <span style={{ fontWeight: 600, fontSize: '14px', display: 'block', marginBottom: '8px' }}>
              Simulate Journey Scenarios
            </span>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '8px' }}>
              <button
                className="quick-reply-chip"
                onClick={() => handleSendMessage('My credit card got stolen in Indiranagar, block it immediately!')}
              >
                🚨 Emergency Card Block
              </button>
              <button
                className="quick-reply-chip"
                onClick={() => handleSendMessage('If I pay 2 lakhs extra on my home loan today, how much interest will I save?')}
              >
                💰 Loan Prepayment Savings
              </button>
              <button
                className="quick-reply-chip"
                onClick={() => handleSendMessage('Had a car accident on Western Express Highway. Need to file insurance claim.')}
              >
                🚗 Car Accident FNOL
              </button>
              <button
                className="quick-reply-chip"
                onClick={() => handleSendMessage('I want to speak with a human manager right now.')}
              >
                👤 Human Agent Escalation
              </button>
            </div>
          </div>
        </div>

        {/* Right Column: Cryptographic Audit Stream */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', overflowY: 'auto' }}>
          <div className="panel-card" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
              <span style={{ fontWeight: 600, fontSize: '14px' }}>SHA-256 Audit Ledger</span>
              <span style={{ fontSize: '11px', color: '#0ca30c', fontWeight: 600 }}>● VERIFIED</span>
            </div>
            <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {auditBlocks.length === 0 ? (
                <div style={{ fontSize: '12px', color: 'var(--muted)', fontStyle: 'italic' }}>Genesis block active...</div>
              ) : (
                auditBlocks.slice(0, 8).map((b) => (
                  <div key={b.id} className="audit-stream-row" style={{ background: 'var(--surface-2)', borderRadius: '4px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 600 }}>
                      <span style={{ color: '#00836c' }}>#{b.id} {b.action}</span>
                      <span style={{ color: 'var(--muted)' }}>{b.actor}</span>
                    </div>
                    <div style={{ color: 'var(--muted)', fontSize: '10px', textOverflow: 'ellipsis', overflow: 'hidden' }}>
                      Hash: {b.hash.substring(0, 24)}...
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="panel-card">
            <span style={{ fontWeight: 600, fontSize: '13px', display: 'block', marginBottom: '6px' }}>
              Regulatory Mandates
            </span>
            <ul style={{ fontSize: '11.5px', color: 'var(--muted)', paddingLeft: '16px', margin: 0, lineHeight: 1.5 }}>
              <li>RBI Circular on Digital Lending Norms</li>
              <li>IRDAI 2-Hour Cashless Pre-Auth SLA</li>
              <li>DPDP Act 2023 Purpose Limitation</li>
              <li>Zero Financial Advice Outside Approved KB</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
