import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";

interface PendingPrediction<T> {
  resolve: (predictions: T[]) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
}

interface WorkerSession<T> {
  child: ChildProcessWithoutNullStreams;
  ready: Promise<void>;
  pending: Map<number, PendingPrediction<T>>;
  fail: (error: Error) => void;
}

interface PredictionWorkerOptions {
  executable: string;
  args: string[];
  name: string;
  requestTimeoutMs?: number;
}

/** A resident prediction process using ready/id JSON messages over standard IO. */
export class PredictionWorker<T> {
  private session: WorkerSession<T> | undefined;
  private sequence = 0;

  constructor(private readonly options: PredictionWorkerOptions) {}

  private start(): WorkerSession<T> {
    const { executable, args, name } = this.options;
    const child = spawn(executable, args, { stdio: ["pipe", "pipe", "pipe"] });
    let resolveReady!: () => void;
    let rejectReady!: (error: Error) => void;
    const ready = new Promise<void>((resolve, reject) => {
      resolveReady = resolve;
      rejectReady = reject;
    });
    const lines = createInterface({ input: child.stdout });
    let stopped = false;
    const session: WorkerSession<T> = {
      child,
      ready,
      pending: new Map(),
      fail: (error) => {
        if (stopped) return;
        stopped = true;
        rejectReady(error);
        lines.close();
        for (const request of session.pending.values()) {
          clearTimeout(request.timer);
          request.reject(error);
        }
        session.pending.clear();
        // An old process may exit after close() has already started a new one.
        if (this.session === session) this.session = undefined;
      },
    };
    lines.on("line", (line) => {
      if (stopped) return;
      let message: Record<string, unknown>;
      try {
        const parsed: unknown = JSON.parse(line);
        if (parsed === null || typeof parsed !== "object") return;
        message = parsed as Record<string, unknown>;
      } catch { return; }
      if (message.ready === true) {
        resolveReady();
        return;
      }
      if (typeof message.id !== "number" || !Number.isInteger(message.id)) return;
      const request = session.pending.get(message.id);
      if (!request) return;
      clearTimeout(request.timer);
      session.pending.delete(message.id);
      if (typeof message.error === "string") request.reject(new Error(`${name}: ${message.error}`));
      else request.resolve(message.predictions as T[]);
    });
    let stderr = "";
    child.stderr.on("data", (chunk) => { stderr = `${stderr}${String(chunk)}`.slice(-4000); });
    child.once("error", session.fail);
    child.once("exit", (code) => {
      session.fail(new Error(`${name} exited with code ${code}${stderr ? `: ${stderr.trim()}` : ""}`));
    });
    child.stdin.on("error", (error) => {
      session.fail(error);
      child.kill("SIGTERM");
    });
    this.session = session;
    return session;
  }

  async predict(images: readonly Buffer[]): Promise<T[]> {
    const session = this.session ?? this.start();
    await session.ready;
    if (this.session !== session) throw new Error(`${this.options.name} is unavailable`);
    const id = ++this.sequence;
    const line = `${JSON.stringify({ id, images: images.map((image) => image.toString("base64")) })}\n`;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        session.pending.delete(id);
        reject(new Error(`${this.options.name} timed out`));
      }, this.options.requestTimeoutMs ?? 15_000);
      session.pending.set(id, { resolve, reject, timer });
      session.child.stdin.write(line);
    });
  }

  close(): void {
    const session = this.session;
    if (!session) return;
    session.fail(new Error(`${this.options.name} is unavailable`));
    if (session.child.exitCode === null) session.child.kill("SIGTERM");
  }
}
