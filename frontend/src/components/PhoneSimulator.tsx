import React, { useState } from 'react';

export interface ChatMessage {
  id: string;
  sender: 'user' | 'bot';
  text: string;
  intent?: string;
  stepUpNeeded?: boolean;
  quickReplies?: string[];
  timestamp: string;
}

interface PhoneSimulatorProps {
  messages: ChatMessage[];
  onSendMessage: (text: string) => void;
  isLoading?: boolean;
}

export function PhoneSimulator({ messages, onSendMessage, isLoading }: PhoneSimulatorProps) {
  const [inputText, setInputText] = useState('');

  const handleSend = () => {
    if (!inputText.trim()) return;
    onSendMessage(inputText);
    setInputText('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSend();
  };

  return (
    <div className="phone-simulator-frame">
      <div className="phone-screen">
        {/* Top Status Bar */}
        <div style={{ background: '#00594a', color: '#a8bab2', padding: '4px 14px', fontSize: '11px', display: 'flex', justifyContent: 'space-between' }}>
          <span>10:45 AM</span>
          <span>● 5G  98%</span>
        </div>

        {/* WhatsApp / Bank Header */}
        <div className="phone-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <div style={{ width: '32px', height: '32px', borderRadius: '50%', background: '#ffffff', color: '#00836c', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 'bold' }}>
              FP
            </div>
            <div>
              <div style={{ fontWeight: 600, fontSize: '13px' }}>FinPulse Bank AI ✓</div>
              <div style={{ fontSize: '10.5px', opacity: 0.85 }}>Official WhatsApp Banking</div>
            </div>
          </div>
          <span style={{ fontSize: '11px', background: 'rgba(255,255,255,0.2)', padding: '2px 8px', borderRadius: '10px' }}>
            Encrypted
          </span>
        </div>

        {/* Message Thread */}
        <div className="phone-messages">
          {messages.map((m) => (
            <div key={m.id} style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <div className={`chat-bubble ${m.sender}`}>
                <div style={{ whiteSpace: 'pre-line' }}>{m.text}</div>
                <div style={{ fontSize: '9.5px', opacity: 0.7, textAlign: 'right', marginTop: '4px' }}>
                  {m.timestamp}
                </div>
              </div>

              {/* Quick Replies if available */}
              {m.sender === 'bot' && m.quickReplies && m.quickReplies.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', margin: '2px 0 6px 4px' }}>
                  {m.quickReplies.map((qr, idx) => (
                    <button
                      key={idx}
                      className="quick-reply-chip"
                      onClick={() => onSendMessage(qr)}
                    >
                      {qr}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}

          {isLoading && (
            <div className="chat-bubble bot" style={{ fontStyle: 'italic', opacity: 0.8 }}>
              FinPulse AI is verifying...
            </div>
          )}
        </div>

        {/* Input Bar */}
        <div style={{ padding: '8px 10px', background: 'var(--surface)', borderTop: '1px solid var(--line)', display: 'flex', gap: '8px', alignItems: 'center' }}>
          <input
            type="text"
            placeholder="Type your message or query..."
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            style={{
              flex: 1,
              padding: '8px 12px',
              borderRadius: '20px',
              border: '1px solid var(--line)',
              fontSize: '13px',
              outline: 'none',
              background: 'var(--surface-2)'
            }}
          />
          <button
            onClick={handleSend}
            style={{
              background: '#00836c',
              color: '#ffffff',
              border: 'none',
              borderRadius: '50%',
              width: '34px',
              height: '34px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 'bold'
            }}
          >
            ➤
          </button>
        </div>
      </div>
    </div>
  );
}
