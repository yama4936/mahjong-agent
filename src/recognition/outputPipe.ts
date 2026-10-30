/**
 * A resident recognizer has no useful work left once its parent has closed
 * the response pipe.  Node emits EPIPE asynchronously on stdout, so handle
 * that terminal condition before a later response turns it into an uncaught
 * exception.  Other stream failures remain fatal and visible.
 */
export function exitWhenOutputPipeBreaks(
  output: NodeJS.WriteStream = process.stdout,
  exit: (code: number) => never = process.exit,
): void {
  let exiting = false;
  output.on("error", (error: NodeJS.ErrnoException) => {
    if (error.code !== "EPIPE") throw error;
    if (!exiting) {
      exiting = true;
      exit(0);
    }
  });
}
