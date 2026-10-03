/** A tag's values on one side of a change: none, the values every file shares, or a sign that the files differ. */
export type Side = string[] | null | "differs";

export type Change = "same" | "changed" | "added" | "removed";

export type Locked = "id" | "rating" | "binary" | "added" | "fixed";

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

export const bytesOf = (value: string) => BYTES.exec(value)?.[1];

export const formatValues = (values: string[]) => values.join("; ");
