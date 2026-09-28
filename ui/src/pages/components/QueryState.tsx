/** Loading and error placeholders for page queries. */
export function ErrorBox({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <p role="alert" className="err">
      {message}
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
