import { describe, expect, it } from "vitest";

import autoClean from "@/test/fixtures/auto-clean/plan.json";
import decisions from "@/test/fixtures/decision-hold/decisions.json";
import decisionHold from "@/test/fixtures/decision-hold/plan.json";
import soundtrackChoice from "@/test/fixtures/soundtrack-choice/plan.json";

import type { DecisionsDoc, PlanDoc } from "./types";

// A JSON import types every string as `string`, so the literal unions of the
// contract are widened before the comparison.
type Loosen<T> = T extends string
	? string
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
};

const noExtraAutoClean: NoExtra<typeof autoClean, Plan> = autoClean;
const noExtraDecisionHold: NoExtra<typeof decisionHold, Plan> = decisionHold;
const noExtraSoundtrackChoice: NoExtra<typeof soundtrackChoice, Plan> =
	soundtrackChoice;

const decisionsDoc = decisions satisfies Loosen<DecisionsDoc>;
const noExtraDecisions: NoExtra<
	typeof decisions,
	Loosen<DecisionsDoc>
> = decisions;

describe("the API types against the engine's fixtures", () => {
	it("holds one album in each plan, and the decision keyed by its source", () => {
		expect(Object.values(plans).map((plan) => plan.albums.length)).toEqual([
			1, 1, 1,
		]);
		expect([
			noExtraAutoClean,
			noExtraDecisionHold,
			noExtraSoundtrackChoice,
		]).toHaveLength(3);
		expect(Object.keys(decisionsDoc.albums)).toEqual([
			decisionHold.albums[0]?.source,
		]);
		expect(noExtraDecisions.job).toBe(decisionHold.job);
	});
});
