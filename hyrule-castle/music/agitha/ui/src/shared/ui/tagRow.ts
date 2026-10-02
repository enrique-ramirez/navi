/** A tag's values on one side of a change: none, the values every file shares, or a sign that the files differ. */
export type Side = string[] | null | "differs";

export type Change = "same" | "changed" | "added" | "removed";

/** Why a tag cannot be edited. `fixed` is one the server will not change and the page cannot say why. */
export type Locked = "id" | "rating" | "binary" | "added" | "fixed";

/** One row of the tag table. */
export interface TagRow {
	key: string;
	now: Side;
	next: Side;
	change: Change;
	locked: Locked | null;
	edited: boolean;
	/** The rules that removed the tag, where the plan did. */
	removedBy: string[];
}

export const BYTES = /\((\d+) bytes\)\s*$/;

/** The size a binary frame shown as text ends with; `undefined` for any other value. */
export const bytesOf = (value: string) => BYTES.exec(value)?.[1];

export const formatValues = (values: string[]) => values.join("; ");
