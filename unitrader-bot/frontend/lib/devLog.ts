/** Log only in development — avoids leaking API errors and tokens in prod DevTools. */

export function devLog(...args: unknown[]): void {
  if (process.env.NODE_ENV !== "production") {
    console.log(...args);
  }
}

export function devWarn(context: string, err?: unknown): void {
  if (process.env.NODE_ENV !== "production") {
    console.warn(context, err);
  }
}

export function devLogError(context: string, err: unknown): void {
  if (process.env.NODE_ENV !== "production") {
    console.error(context, err);
  }
}
