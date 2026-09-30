import { describe, expect, it } from "vitest";

import autoClean from "@/test/fixtures/auto-clean/plan.json";
import decisions from "@/test/fixtures/decision-hold/decisions.json";
import decisionHold from "@/test/fixtures/decision-hold/plan.json";
import missingDecisions from "@/test/fixtures/missing-track/decisions.json";
import missingTrack from "@/test/fixtures/missing-track/plan.json";
import soundtrackChoice from "@/test/fixtures/soundtrack-choice/plan.json";
import strayImageDecisions from "@/test/fixtures/stray-images/decisions.json";
import strayImages from "@/test/fixtures/stray-images/plan.json";

import type { DecisionsDoc, PlanDoc, StrayWhy } from "./types";

// A JSON import types every string as `string` and every boolean as `boolean`,
// so the literal types of the contract are widened before the comparison.
type Loosen<T> = T extends string
	? string
	: T extends boolean
		? boolean
		: T extends readonly (infer U)[]
			? Loosen<U>[]
			: T extends object
				? { [K in keyof T]: Loosen<T[K]> }
				: T;

// A key of a union that some member has.
type KeyOf<T> = T extends unknown ? keyof T : never;
type ValueAt<T, K extends PropertyKey> = T extends unknown
	? K extends keyof T
		? T[K]
		: never
	: never;

// `satisfies` ignores keys the contract lacks, so a field the engine adds would
// pass unseen. Any key of the fixture that the contract does not name becomes
// `never` here, and the assignment below fails on it.
type NoExtra<Actual, Declared> = Actual extends readonly (infer A)[]
	? Extract<Declared, readonly unknown[]> extends readonly (infer D)[]
		? NoExtra<A, D>[]
		: never
	: Actual extends object
		? {
				[K in keyof Actual]: K extends KeyOf<Extract<Declared, object>>
					? NoExtra<Actual[K], ValueAt<Extract<Declared, object>, K>>
					: never;
			}
		: Actual;

type Plan = Loosen<PlanDoc>;

const plans = {
	autoClean: autoClean satisfies Plan,
	decisionHold: decisionHold satisfies Plan,
	soundtrackChoice: soundtrackChoice satisfies Plan,
	missingTrack: missingTrack satisfies Plan,
	strayImages: strayImages satisfies Plan,
};

const noExtraAutoClean: NoExtra<typeof autoClean, Plan> = autoClean;
const noExtraDecisionHold: NoExtra<typeof decisionHold, Plan> = decisionHold;
const noExtraSoundtrackChoice: NoExtra<typeof soundtrackChoice, Plan> =
	soundtrackChoice;
const noExtraMissingTrack: NoExtra<typeof missingTrack, Plan> = missingTrack;
const noExtraStrayImages: NoExtra<typeof strayImages, Plan> = strayImages;

const decisionsDoc = decisions satisfies Loosen<DecisionsDoc>;
const noExtraDecisions: NoExtra<
	typeof decisions,
	Loosen<DecisionsDoc>
> = decisions;
const missingDecisionsDoc = missingDecisions satisfies Loosen<DecisionsDoc>;
const noExtraMissingDecisions: NoExtra<
	typeof missingDecisions,
	Loosen<DecisionsDoc>
> = missingDecisions;
const strayImageDecisionsDoc =
	strayImageDecisions satisfies Loosen<DecisionsDoc>;
const noExtraStrayImageDecisions: NoExtra<
	typeof strayImageDecisions,
	Loosen<DecisionsDoc>
> = strayImageDecisions;

describe("the API types against the engine's fixtures", () => {
	it("holds one album in each plan, and the decision keyed by its source", () => {
		expect(Object.values(plans).map((plan) => plan.albums.length)).toEqual([
			1, 1, 1, 1, 1,
		]);
		expect([
			noExtraAutoClean,
			noExtraDecisionHold,
			noExtraSoundtrackChoice,
			noExtraMissingTrack,
			noExtraStrayImages,
		]).toHaveLength(5);
		expect(Object.keys(decisionsDoc.albums)).toEqual([
			decisionHold.albums[0]?.source,
		]);
		expect(noExtraDecisions.job).toBe(decisionHold.job);
		expect(Object.keys(missingDecisionsDoc.albums)).toEqual([
			missingTrack.albums[0]?.source,
		]);
		expect(noExtraMissingDecisions.job).toBe(missingTrack.job);
		expect(Object.keys(strayImageDecisionsDoc.albums)).toEqual([
			strayImages.albums[0]?.source,
		]);
		expect(noExtraStrayImageDecisions.job).toBe(strayImages.job);
	});

	// The generated fixture is only a check of the contract where the engine
	// really wrote each answer: a reason it stops producing leaves `StrayWhy`
	// unchecked against it.
	it("carries every reason the engine gives a stray, from a real identify", () => {
		const reasons: StrayWhy[] = [
			"guessed",
			"copy",
			"lost",
			"won",
			"owner",
			"no guess",
		];
		expect(
			new Set(strayImages.albums[0]?.strays.map((stray) => stray.why)),
		).toEqual(new Set(reasons));
		expect(Object.values(noExtraStrayImageDecisions.albums)[0]?.strays).toEqual(
			{ "COVERS/IMG_0002.jpg": "booklet-01.jpg" },
		);
	});

	it("holds the album with an unreadable track on a missing hold that names it, from a real identify", () => {
		expect(
			missingTrack.albums[0]?.holds.filter((hold) => hold.kind === "missing"),
		).toEqual([
			{
				kind: "missing",
				detail: 'track 2, "Two": 02 two.mp3 could be it, but it cannot be read',
			},
		]);
	});
});
