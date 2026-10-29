import { readFile, writeFile } from "node:fs/promises";
import { layoutSchema } from "../recognition/layout.js";
import { collectHandTemplates } from "../recognition/templateCollector.js";
import { AUTO_MINIMUM_HOLDOUTS, validateTemplateDirectory } from "../recognition/templateValidator.js";
import type { CliArguments, CliCommand } from "./arguments.js";

async function collectTemplates(args: CliArguments): Promise<void> {
  const screenshot = args.values[0];
  const layoutPath = args.values[1];
  const labels = args.values[2]?.split(",");
  const output = args.values.slice(3).find((argument) => !argument.startsWith("--")) ?? "templates";
  const splitValue = args.option("--split") ?? "train";
  if (!screenshot || !layoutPath || !labels) throw new Error("Usage: collect-templates <screenshot> <layout> <comma-separated tiles> [output] [--split=train|holdout]");
  if (splitValue !== "train" && splitValue !== "holdout") throw new Error(`Invalid template split: ${splitValue}`);
  const layout = layoutSchema.parse(JSON.parse(await readFile(layoutPath, "utf8")));
  console.log(JSON.stringify(await collectHandTemplates(screenshot, layout, labels, output, splitValue), null, 2));
}

async function validateTemplates(args: CliArguments): Promise<void> {
  const path = args.values[0];
  if (!path) throw new Error("Usage: validate-templates <templates> [--holdout=pattern] [--max-per-class=N]");
  const holdout = args.option("--holdout") ?? "(?:capture|holdout|test)";
  const maxPerClass = Number(args.option("--max-per-class") ?? Number.POSITIVE_INFINITY);
  const orientationValue = args.option("--orientation") ?? "any";
  if (orientationValue !== "any" && orientationValue !== "upright") throw new Error(`Invalid orientation: ${orientationValue}`);
  const tileMatcher = layoutSchema.shape.tileMatcher.parse(args.option("--matcher"));
  const report = await validateTemplateDirectory(path, { holdoutPattern: new RegExp(holdout, "i"), maxPerClass, orientation: orientationValue, tileMatcher });
  const output = args.option("--output");
  if (output) await writeFile(output, JSON.stringify(report, null, 2), { encoding: "utf8", mode: 0o600 });
  console.log(JSON.stringify(output ? {
    output,
    total: report.total,
    accuracy: report.accuracy,
    automationSafeRate: report.automationSafeRate,
    passesAutoCalibration: report.passesAutoCalibration,
    crossLabelCollisions: report.crossLabelCollisions.length,
  } : report, null, 2));
}

async function certifyLayout(args: CliArguments): Promise<void> {
  const path = args.values[0];
  const reportPath = args.values[1];
  const outputPath = args.values[2];
  if (!path || !reportPath || !outputPath) throw new Error("Usage: certify-layout <layout.json> <validation-report.json> <output-layout.json>");
  const layout = layoutSchema.parse(JSON.parse(await readFile(path, "utf8")));
  const report = JSON.parse(await readFile(reportPath, "utf8"));
  if (report.matcherVersion !== "2" || report.tileMatcher !== layout.tileMatcher) {
    throw new Error("Validation matcher/version does not match layout; rerun validation");
  }
  if (report.passesAutoCalibration !== true || report.accuracy !== 1 || report.automationSafeRate !== 1 || report.total < AUTO_MINIMUM_HOLDOUTS) {
    throw new Error("Validation report does not satisfy Auto calibration requirements");
  }
  const certified = layoutSchema.parse({
    ...layout,
    autoOperation: {
      enabled: true,
      recognizer: "template",
      matcherVersion: report.matcherVersion,
      tileMatcher: report.tileMatcher,
      samples: report.total,
      accuracy: report.accuracy,
      automationSafeRate: report.automationSafeRate,
      validatedAt: new Date().toISOString(),
      templateSetFingerprint: report.templateSetFingerprint,
    },
  });
  await writeFile(outputPath, JSON.stringify(certified, null, 2), { encoding: "utf8", mode: 0o600 });
  console.log(JSON.stringify({ certifiedLayout: outputPath, templateSetFingerprint: report.templateSetFingerprint }, null, 2));
}

export const commands: Record<string, CliCommand> = {
  "collect-templates": collectTemplates,
  "validate-templates": validateTemplates,
  "certify-layout": certifyLayout,
};
