import { CliArguments, type CliCommand } from "./arguments.js";

type CommandModule = { commands: Record<string, CliCommand> };
const loaders = {
  adviceCommands: () => import("./adviceCommands.js"),
  frameCommands: () => import("./frameCommands.js"),
  recognitionCommands: () => import("./recognitionCommands.js"),
  liveCommands: () => import("./liveCommands.js"),
  replayCommands: () => import("./replayCommands.js"),
  templateCommands: () => import("./templateCommands.js"),
} satisfies Record<string, () => Promise<CommandModule>>;

const commandGroups = new Map<string, keyof typeof loaders>([
  ["advise", "adviceCommands"],
  ["jev-smoke", "adviceCommands"],
  ["jev-tune", "replayCommands"],
  ["recognize", "recognitionCommands"],
  ["evaluate-frame", "frameCommands"],
  ["verify-discard-frame", "frameCommands"],
  ["detect-regions", "recognitionCommands"],
  ["recognize-regions", "recognitionCommands"],
  ["public-observation", "recognitionCommands"],
  ["recognize-center", "recognitionCommands"],
  ["recognize-actions", "recognitionCommands"],
  ["propose-hand-layout", "recognitionCommands"],
  ["analyze-screenshot", "frameCommands"],
  ["watch-hand-layout", "liveCommands"],
  ["live-advisor", "liveCommands"],
  ["replay", "replayCommands"],
  ["attach-result", "replayCommands"],
  ["benchmark", "replayCommands"],
  ["policy-compare", "replayCommands"],
  ["collect-templates", "templateCommands"],
  ["validate-templates", "templateCommands"],
  ["certify-layout", "templateCommands"],
  ["turn", "liveCommands"],
  ["watch", "liveCommands"],
]);

export async function runCli(argv: readonly string[]): Promise<void> {
  const [command, ...values] = argv;
  const group = command === undefined ? undefined : commandGroups.get(command);
  if (!group || !command) throw new Error(`Commands: ${[...commandGroups.keys()].join(", ")}`);
  const { commands } = await loaders[group]();
  await commands[command]!(new CliArguments(command, values));
}
