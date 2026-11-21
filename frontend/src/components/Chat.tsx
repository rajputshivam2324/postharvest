import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ArrowUp, LoaderCircle, Sparkles, X } from 'lucide-react';
import { api } from '../api/client';
import type { ChatRequest, ChatResponse } from '../api/types';

type Turn =
  | { role: 'user'; content: string }
  | { role: 'assistant'; content: string; reply: ChatResponse }
  | { role: 'error'; content: string };

const STARTERS = {
  batch: [
    'How has temperature changed in the last 24 hours?',
    'Is the gas reading rising?',
    'What did staff last observe?',
  ],
  portfolio: [
    'Which batch needs inspection first?',
    'Are any devices offline?',
    'Which alerts are open?',
  ],
};
const MODE_LABEL: Record<ChatResponse['mode'], string> = {
  ai: 'AI answer from your records',
  summary: 'Summary of your records',
  policy: 'This tool does not decide that',
};

function Reply({
  reply,
  send,
  latest,
}: {
  reply: ChatResponse;
  send: (text: string) => void;
  /** Only the newest answer offers follow-ups; older ones would just pile up. */
  latest: boolean;
}) {
  return (
    <>
      <span className={`chat-mode ${reply.mode}`}>{MODE_LABEL[reply.mode]}</span>
      {/* Plain text only: model output and staff notes are never rendered as HTML. */}
      <ChatText text={reply.answer} />
      {reply.notice && <p className="chat-notice">{reply.notice}</p>}
      {reply.sources.length > 0 && (
        <ul className="chat-sources" aria-label="Sources">
          {reply.sources.map((source) => (
            <li key={source.id}>
              {source.batch_id ? (
                <Link to={`/app/batches/${source.batch_id}`}>{source.label}</Link>
              ) : (
                <span>{source.label}</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {latest && reply.follow_ups.length > 0 && (
        <div className="chat-followups">
          {reply.follow_ups.map((question) => (
            <button key={question} type="button" onClick={() => send(question)}>
              {question}
            </button>
          ))}
        </div>
      )}
    </>
  );
}

/** Renders paragraphs and "- " lines as plain React nodes; model output is never HTML. */
export function ChatText({ text }: { text: string }) {
  const blocks: { list: boolean; lines: string[] }[] = [];
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    const bullet = /^[-*•]\s+/.test(line);
    const last = blocks[blocks.length - 1];
    const body = bullet ? line.replace(/^[-*•]\s+/, '') : line;
    if (last && last.list === bullet && bullet) last.lines.push(body);
    else blocks.push({ list: bullet, lines: [body] });
  }
  return (
    <div className="chat-text">
      {blocks.map((block, index) =>
        block.list ? (
          <ul key={index}>
            {block.lines.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        ) : (
          <p key={index}>{block.lines.join(' ')}</p>
        ),
      )}
    </div>
  );
}

export function ChatPanel({
  batchId,
  close,
}: {
  /** The batch page being viewed, if any; the person can still widen the question. */
  batchId?: string;
  close: () => void;
}) {
  const [wide, setWide] = useState(false);
  const scope = batchId && !wide ? batchId : undefined;
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState('');
  const input = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const ask = useMutation({
    mutationFn: (body: ChatRequest) => api<ChatResponse>('/chat', { method: 'POST', body }),
  });

  useEffect(() => {
    input.current?.focus();
  }, []);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: 'end' });
  }, [turns, ask.isPending]);
  // A different scope is a different conversation.
  useEffect(() => {
    setTurns([]);
    ask.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope]);

  function send(text: string) {
    const message = text.trim();
    if (!message || ask.isPending) return;
    const history = turns
      .filter((t): t is Exclude<Turn, { role: 'error' }> => t.role !== 'error')
      .slice(-6)
      .map((t) => ({ role: t.role, content: t.content.slice(0, 2000) }));
    setTurns((all) => [...all, { role: 'user', content: message }]);
    setDraft('');
    ask.mutate(
      { message, ...(scope ? { batch_id: scope } : {}), history },
      {
        onSuccess: (reply) =>
          setTurns((all) => [...all, { role: 'assistant', content: reply.answer, reply }]),
        onError: (error) =>
          setTurns((all) => [
            ...all,
            { role: 'error', content: error.message || 'The question could not be answered.' },
          ]),
      },
    );
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    send(draft);
  }
  function keys(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      send(draft);
    }
  }
  const starters = scope ? STARTERS.batch : STARTERS.portfolio;
  return (
    <aside className="chat-panel" aria-label="Ask your data">
      <header>
        <div>
          <h2>
            <Sparkles size={17} /> Ask your data
          </h2>
          <p>
            {scope
              ? 'Answering about this batch'
              : batchId
                ? 'Answering about every batch you can see'
                : 'Answering about the batches you can see'}
          </p>
        </div>
        <button className="icon-button" onClick={close} aria-label="Close chat">
          <X size={19} />
        </button>
      </header>
      {batchId && (
        <label className="chat-scope">
          <input type="checkbox" checked={wide} onChange={(e) => setWide(e.target.checked)} /> Ask
          about all batches instead
        </label>
      )}
      <div className="chat-log" role="log" aria-live="polite" aria-label="Conversation">
        {turns.length === 0 && (
          <div className="chat-empty">
            <p>
              Ask in plain language. Answers come only from your batches, readings, observations and
              alerts, and name where they came from.
            </p>
            <div className="chat-followups">
              {starters.map((question) => (
                <button key={question} type="button" onClick={() => send(question)}>
                  {question}
                </button>
              ))}
            </div>
          </div>
        )}
        {turns.map((turn, index) => (
          <div key={index} className={`chat-turn ${turn.role}`}>
            {turn.role === 'assistant' ? (
              <Reply reply={turn.reply} send={send} latest={index === turns.length - 1} />
            ) : (
              <p className="chat-text" role={turn.role === 'error' ? 'alert' : undefined}>
                {turn.content}
              </p>
            )}
          </div>
        ))}
        {ask.isPending && (
          <div className="chat-turn assistant" role="status">
            <p className="chat-text">
              <LoaderCircle size={15} className="spin" /> Reading your records…
            </p>
          </div>
        )}
        <div ref={end} />
      </div>
      <form onSubmit={submit}>
        <label className="visually-hidden" htmlFor="chat-input">
          Your question
        </label>
        <textarea
          id="chat-input"
          ref={input}
          rows={2}
          maxLength={1000}
          value={draft}
          placeholder="Ask about readings, alerts or what to inspect"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={keys}
        />
        <button
          className="button primary"
          disabled={!draft.trim() || ask.isPending}
          aria-label="Send question"
        >
          <ArrowUp size={18} />
        </button>
      </form>
      <p className="chat-foot">
        Decision support from uncalibrated sensors. It does not certify safety or shelf life; a
        person should inspect the produce.
      </p>
    </aside>
  );
}
