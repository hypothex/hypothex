/** Loading and error placeholders for page queries. */
export function ErrorBox({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);
  // Match only the API transport envelope, preserving colons/arrows in the cause.
  const visible = message.replace(/^(?:GET|POST|PUT|DELETE) \/(?:api\/v1(?:\/|\?)|\.well-known\/hypothex\/)\S* → [45]\d{2}: /, "");
  return (
    <p role="alert" className="err" title={message}>
      {visible}
    </p>
  );
}

export function Loading() {
  return (
    <p className="small" aria-busy="true">
      loading…
    </p>
  );
}
