import path from "node:path";
import { PredictionWorker } from "./predictionWorker.js";

/** Resident OCR probe; all values are unverified image candidates. */
export class SanmaBoardWorker {
  private readonly worker = new PredictionWorker<unknown>({
    executable: path.resolve(".runtime/python-auto-venv/bin/python"),
    args: [path.resolve("python/sanma_board_worker.py")],
    name: "sanma board worker", requestTimeoutMs: 30_000,
  });
  async observe(frame: Buffer): Promise<unknown> {
    try {
      const predictions = await this.worker.predict([frame]);
      if (!Array.isArray(predictions) || predictions.length !== 1) throw new Error("Unexpected sanma board output");
      return predictions[0];
    } catch (error) {
      // Discard a timed-out or broken worker; a later request may start fresh.
      this.worker.close();
      throw error;
    }
  }
  close(): void { this.worker.close(); }
}
