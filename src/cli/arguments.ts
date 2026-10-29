/** Arguments after the command, preserving positional and first-option semantics. */
export class CliArguments {
  constructor(readonly command: string, readonly values: readonly string[]) {}

  option(name: string): string | undefined {
    const prefix = `${name}=`;
    return this.values.find((value) => value.startsWith(prefix))?.slice(prefix.length);
  }

  has(flag: string): boolean {
    return this.values.includes(flag);
  }
}

export type CliCommand = (args: CliArguments) => Promise<void>;
