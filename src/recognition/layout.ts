import { z } from "zod";

const rectSchema = z.object({
  x: z.number().int().nonnegative(),
  y: z.number().int().nonnegative(),
  width: z.number().int().positive(),
  height: z.number().int().positive(),
});

const publicTileRegionSchema = rectSchema.extend({
  rotationToUpright: z.union([z.literal(0), z.literal(90), z.literal(180), z.literal(270)]).default(0),
  detectionMode: z.literal("discard_grid").optional(),
});

const publicTileRegionsSchema = z.object({
  doraIndicators: publicTileRegionSchema.optional(),
  ownDiscards: publicTileRegionSchema.optional(),
  rightDiscards: publicTileRegionSchema.optional(),
  oppositeDiscards: publicTileRegionSchema.optional(),
  leftDiscards: publicTileRegionSchema.optional(),
  ownMelds: publicTileRegionSchema.optional(),
  rightMelds: publicTileRegionSchema.optional(),
  oppositeMelds: publicTileRegionSchema.optional(),
  leftMelds: publicTileRegionSchema.optional(),
});

const actionButtonRegionsSchema = z.object({
  riichi: rectSchema.optional(),
  tsumo: rectSchema.optional(),
  ron: rectSchema.optional(),
  chi: rectSchema.optional(),
  pon: rectSchema.optional(),
  kan: rectSchema.optional(),
  kyuushu: rectSchema.optional(),
  pass: rectSchema.optional(),
});

const centerBoardRegionsSchema = z.object({
  round: publicTileRegionSchema,
  honba: publicTileRegionSchema,
  riichiSticks: publicTileRegionSchema,
  remainingTiles: publicTileRegionSchema,
  ownSeat: publicTileRegionSchema,
  ownScore: publicTileRegionSchema,
  rightScore: publicTileRegionSchema,
  oppositeScore: publicTileRegionSchema,
  leftScore: publicTileRegionSchema,
});

const actionCertificateSchema = z.object({
  enabled: z.literal(true),
  samples: z.number().int().min(20),
  accuracy: z.literal(1),
  falsePositiveRate: z.literal(0),
  validatedAt: z.iso.datetime(),
  templateSetFingerprint: z.string().regex(/^[a-f0-9]{64}$/),
});

export const layoutSchema = z.object({
  viewport: z.object({ width: z.number().int().positive(), height: z.number().int().positive() }),
  handSlots: z.array(rectSchema).min(13).max(14),
  drawSlot: rectSchema.optional(),
  clickPoints: z.array(z.object({ x: z.number(), y: z.number() })).min(13).max(14),
  minimumTileConfidence: z.number().min(0).max(1).default(0.98),
  minimumTilePresence: z.number().min(0).max(1).default(0.12),
  tileMatcher: z.enum(["raw", "face", "face_all"]).default("raw"),
  minimumVitConfidence: z.number().min(0).max(1).default(0.5),
  minimumVitMargin: z.number().min(0).max(1).default(0.05),
  publicTileRegions: publicTileRegionsSchema.optional(),
  centerBoardRegions: centerBoardRegionsSchema.optional(),
  actionButtonRegions: actionButtonRegionsSchema.optional(),
  actionOperation: z.object({
    riichi: actionCertificateSchema.optional(),
    tsumo: actionCertificateSchema.optional(),
    ron: actionCertificateSchema.optional(),
    chi: actionCertificateSchema.optional(),
    pon: actionCertificateSchema.optional(),
    kan: actionCertificateSchema.optional(),
    kyuushu: actionCertificateSchema.optional(),
    pass: actionCertificateSchema.optional(),
  }).optional(),
  autoOperation: z.object({
    enabled: z.literal(true),
    recognizer: z.literal("template").default("template"),
    matcherVersion: z.literal("2"),
    tileMatcher: z.enum(["raw", "face", "face_all"]),
    samples: z.number().int().min(185),
    accuracy: z.literal(1),
    automationSafeRate: z.literal(1),
    validatedAt: z.iso.datetime(),
    templateSetFingerprint: z.string().regex(/^[a-f0-9]{64}$/),
  }).optional(),
});

export type ScreenLayout = z.infer<typeof layoutSchema>;
export type Rect = z.infer<typeof rectSchema>;
export type PublicTileRegionName = keyof NonNullable<ScreenLayout["publicTileRegions"]>;
export type PublicTileRegion = NonNullable<NonNullable<ScreenLayout["publicTileRegions"]>[PublicTileRegionName]>;
