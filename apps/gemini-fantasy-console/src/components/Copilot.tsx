import { ChangeEvent, FormEvent, useState } from 'react';
import { Bot, Send, X } from 'lucide-react';
import { api } from '../lib/api';

export function Copilot({ leagueId, rosterId }: { leagueId?: string; rosterId?: string }) {
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState('What is the highest-leverage move for my roster this week?');
  const [answer, setAnswer] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setAnswer('');
    try { setAnswer((await api.copilot(message, leagueId, rosterId)).text); }
    catch (error) { setAnswer(error instanceof Error ? error.message : 'Copilot unavailable'); }
    finally { setBusy(false); }
  }

  return <>
    <button className="copilot-launch" onClick={() => setOpen(true)}><Bot size={18}/> Ask Fourth Down</button>
    {open && <aside className="copilot-drawer">
      <div className="copilot-header"><div><span className="eyebrow">Gemini tool orchestrator</span><h2>Fourth Down Copilot</h2></div><button className="icon-button" onClick={() => setOpen(false)}><X/></button></div>
      <div className="copilot-body">
        <p className="muted">Copilot calls deterministic league, projection, trade, waiver, and lineup tools. It never invents player values.</p>
        {answer && <div className="copilot-answer">{answer}</div>}
      </div>
      <form className="copilot-form" onSubmit={submit}>
        <textarea value={message} onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setMessage(event.target.value)} />
        <button disabled={busy || !message.trim()}>{busy ? 'Thinking…' : <><Send size={16}/> Send</>}</button>
      </form>
    </aside>}
  </>;
}
