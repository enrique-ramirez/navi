import { useId, useState } from "react";

import styles from "./SuggestInput.module.css";

const LIMIT = 12;

const fold = (text: string) => text.trim().toLowerCase();

/** The text up to and including the last `;`, and the value being typed after it. */
export function typedValue(text: string) {
	const at = text.lastIndexOf(";");
	return { before: text.slice(0, at + 1), term: text.slice(at + 1).trim() };
}

/** The options the value being typed could be: those that start with it, then those that hold it, less the ones already typed. */
export function suggestionsFor(options: readonly string[], text: string) {
	const { before, term } = typedValue(text);
	const wanted = fold(term);
	if (!wanted) return [];
	const held = new Set(before.split(";").map(fold));
	const open = options.filter((option) => !held.has(fold(option)));
	return [
		...open.filter((option) => fold(option).startsWith(wanted)),
		...open.filter(
			(option) =>
				!fold(option).startsWith(wanted) && fold(option).includes(wanted),
		),
	].slice(0, LIMIT);
}

/** The options as they were looked up for the value being typed, less the ones already typed. */
export function lookedUp(options: readonly string[], text: string) {
	const { before, term } = typedValue(text);
	if (!term) return [];
	const held = new Set(before.split(";").map(fold));
	return options.filter((option) => !held.has(fold(option))).slice(0, LIMIT);
}

/** Options looked up from the value being typed, in place of a list known beforehand. */
export interface Lookup {
	/** The answer to the last search. */
	options: readonly string[];
	/** What an option shows beside itself, to tell it from another of the same name. */
	hintOf: (option: string) => string | undefined;
	/** Asks for the options of `term`, the value being typed. */
	search: (term: string) => void;
	/** What the search is doing or found, said under the options; `null` where there is nothing to say. */
	status: { text: string; retry?: { label: string; run: () => void } } | null;
}

/** `text` with the value being typed replaced by `option`, ready for the next value. */
export const withPicked = (text: string, option: string) => {
	const { before } = typedValue(text);
	return `${before ? `${before} ` : ""}${option}; `;
};

/**
 * A text field of `;`-separated values that offers options for the value
 * being typed: those of `options` that fit it, or whatever `lookup` found
 * for it. Picking one writes it with the separator after it, so the next
 * value can be typed straight away.
 */
export function SuggestInput({
	className,
	label,
	value,
	placeholder,
	options,
	lookup,
	onChange,
	onCommit,
	onCancel,
}: {
	className?: string;
	label: string;
	value: string;
	placeholder?: string;
	options: readonly string[];
	lookup?: Lookup;
	onChange: (text: string) => void;
	/** Enter with no suggestion chosen, or the field left. */
	onCommit: () => void;
	/** Escape with the list closed. */
	onCancel: () => void;
}) {
	const list = useId();
	const [focused, setFocused] = useState(false);
	const [closed, setClosed] = useState(false);
	const [active, setActive] = useState(-1);

	const found = lookup
		? lookedUp(lookup.options, value)
		: suggestionsFor(options, value);
	const status = lookup && typedValue(value).term ? lookup.status : null;
	const listed = focused && !closed && found.length > 0;
	const open = listed || (focused && !closed && status !== null);
	const chosen = listed ? found[active] : undefined;

	function pick(option: string) {
		onChange(withPicked(value, option));
		lookup?.search("");
		setActive(-1);
	}

	return (
		<span className={styles.field}>
			<input
				className={className}
				aria-label={label}
				aria-autocomplete="list"
				aria-controls={listed ? list : undefined}
				aria-activedescendant={
					chosen === undefined ? undefined : `${list}-${active}`
				}
				autoComplete="off"
				value={value}
				placeholder={placeholder}
				onFocus={() => {
					setFocused(true);
					// One search serves every field of its kind: this one's own value is what it is about now.
					lookup?.search(typedValue(value).term);
				}}
				onBlur={() => {
					setFocused(false);
					setClosed(false);
					setActive(-1);
					onCommit();
				}}
				onChange={(event) => {
					setClosed(false);
					setActive(-1);
					lookup?.search(typedValue(event.target.value).term);
					onChange(event.target.value);
				}}
				onKeyDown={(event) => {
					if (event.key === "ArrowDown" && listed) {
						event.preventDefault();
						setActive((active + 1) % found.length);
					} else if (event.key === "ArrowUp" && listed) {
						event.preventDefault();
						setActive((active <= 0 ? found.length : active) - 1);
					} else if (event.key === "Enter") {
						event.preventDefault();
						if (chosen === undefined) onCommit();
						else pick(chosen);
					} else if (event.key === "Escape") {
						if (open) setClosed(true);
						else onCancel();
					}
				}}
			/>
			{open && (
				<div className={styles.list}>
					{listed && (
						<div id={list} role="listbox" aria-label={label}>
							{found.map((option, at) => (
								// biome-ignore lint/a11y/useKeyWithClickEvents: the field holds the focus and its arrow keys and Enter pick an option
								<div
									key={option}
									id={`${list}-${at}`}
									role="option"
									tabIndex={-1}
									aria-selected={at === active}
									className={styles.option}
									// The field keeps the focus, so leaving it is not taken for a commit.
									onMouseDown={(event) => event.preventDefault()}
									onClick={() => pick(option)}
								>
									{option}
									{lookup?.hintOf(option) && (
										<span className={styles.hint}>{lookup.hintOf(option)}</span>
									)}
								</div>
							))}
						</div>
					)}
					{status && (
						<div role="status" className={styles.status}>
							{status.text}
							{status.retry && (
								<button
									type="button"
									className={styles.retry}
									onMouseDown={(event) => event.preventDefault()}
									onClick={status.retry.run}
								>
									{status.retry.label}
								</button>
							)}
						</div>
					)}
				</div>
			)}
		</span>
	);
}
