import { useEffect, useRef, type ReactNode } from 'react';
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Inbox,
  Leaf,
  LoaderCircle,
  RefreshCw,
  X,
} from 'lucide-react';
import type { UseQueryResult } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import type { BatchOut } from '../api/types';

export const statusLabels: Record<BatchOut['status'], string> = {
  unknown: 'Not assessed',
  fresh: 'Low risk',
  early_decay: 'Elevated risk',
  spoiling: 'High risk',
  insufficient_data: 'Insufficient evidence',
};
export const date = (value: string | null | undefined) =>
  value
    ? new Date(value).toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : 'Not recorded';
export const human = (value: string) => value.replaceAll('_', ' ');
export function Brand() {
  return (
    <Link to="/" className="brand">
      <span className="brand-mark">
        <Leaf size={22} />
      </span>
      harvest<span className="brand-period">.</span>
    </Link>
  );
}
export function Badge({ status }: { status: BatchOut['status'] }) {
  return (
    <span className={`badge ${status}`}>
      <span className="status-dot" />
      {statusLabels[status]}
    </span>
  );
}
export function Source({ simulated }: { simulated: boolean }) {
  return (
    <span className={`source ${simulated ? 'simulated' : ''}`}>
      {simulated ? 'Simulated' : 'Hardware'}
    </span>
  );
}
export function Notice({ children, danger = false }: { children: ReactNode; danger?: boolean }) {
  return (
    <div className={`notice ${danger ? 'danger' : ''}`} role={danger ? 'alert' : 'status'}>
      <AlertCircle size={18} />
      <div>{children}</div>
    </div>
  );
}
export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <Inbox size={30} />
      <h3>{title}</h3>
      <div>{children}</div>
    </div>
  );
}
export function QueryState({
  query,
  empty,
  children,
}: {
  query: Pick<
    UseQueryResult,
    'isPending' | 'isError' | 'error' | 'refetch' | 'data' | 'isFetching' | 'dataUpdatedAt'
  >;
  empty?: boolean;
  children: ReactNode;
}) {
  if (query.isPending)
    return (
      <div className="loading" role="status">
        <LoaderCircle size={22} className="spin" /> Loading records…
      </div>
    );
  if (query.isError && !query.data)
    return (
      <Notice danger>
        {query.error?.message || 'Unable to load records.'}{' '}
        <button className="text-button" onClick={() => void query.refetch()}>
          Try again
        </button>
      </Notice>
    );
  return (
    <>
      {query.isError && (
        <Notice danger>
          Refresh failed. Showing previously loaded records from{' '}
          {date(new Date(query.dataUpdatedAt).toISOString())}.{' '}
          <button className="text-button" onClick={() => void query.refetch()}>
            Retry
          </button>
        </Notice>
      )}
      {empty ? (
        <Empty title="No records yet">Records will appear here when available.</Empty>
      ) : (
        children
      )}
    </>
  );
}
export function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className="actions">{action}</div>
    </div>
  );
}
export function Refresh({ refresh, fetching }: { refresh: () => void; fetching: boolean }) {
  return (
    <button className="button secondary" onClick={refresh} disabled={fetching}>
      <RefreshCw size={16} className={fetching ? 'spin' : ''} /> Refresh
    </button>
  );
}
export function Pagination({
  total,
  offset,
  limit = 12,
  onChange,
}: {
  total: number;
  offset: number;
  limit?: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="pagination">
      <span>
        {total ? `${offset + 1}–${Math.min(offset + limit, total)} of ${total}` : '0 records'}
      </span>
      <div>
        <button
          aria-label="Previous page"
          disabled={offset === 0}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          <ArrowLeft size={17} />
        </button>
        <button
          aria-label="Next page"
          disabled={offset + limit >= total}
          onClick={() => onChange(offset + limit)}
        >
          <ArrowRight size={17} />
        </button>
      </div>
    </div>
  );
}
export function Modal({
  title,
  close,
  children,
  wide,
}: {
  title: string;
  close: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    dialog.current?.showModal();
    return () => {
      dialog.current?.close();
      previous?.focus();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className={wide ? 'wide' : undefined}
      onCancel={close}
      onClick={(event) => {
        if (event.target === dialog.current) close();
      }}
      aria-labelledby="dialog-title"
    >
      <div className="modal-heading">
        <h2 id="dialog-title">{title}</h2>
        <button type="button" className="icon-button" onClick={close} aria-label="Close dialog">
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function Safety() {
  return (
    <div className="safety">
      <AlertCircle size={16} />
      <span>
        Risk indicators support human inspection. They do not certify food safety or remaining shelf
        life.
      </span>
    </div>
  );
}
