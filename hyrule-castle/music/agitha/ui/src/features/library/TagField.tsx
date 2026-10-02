import { useId, useState } from "react";

import styles from "./Panel.module.css";

/**
 * A text field that hands its text to `onCommit` on Enter and empties itself
 * where the commit was taken. Given `suggestions`, it offers them as a list.
 */
export function TagField({
	label,
	placeholder,
	suggestions,
	onCommit,
}: {
	label: string;
	/** What the field is for, in words a sighted reader sees; `label` is the name it is heard by. */
	placeholder: string;
	suggestions?: string[];
	onCommit: (value: string) => boolean;
}) {
	const list = useId();
	const [text, setText] = useState("");

	return (
		<>
			<input
				className={styles.input}
				aria-label={label}
				placeholder={placeholder}
				list={suggestions ? list : undefined}
				value={text}
				onChange={(event) => setText(event.target.value)}
				onKeyDown={(event) => {
					if (event.key !== "Enter") return;
					event.preventDefault();
					if (onCommit(text.trim())) setText("");
				}}
			/>
			{suggestions && (
				<datalist id={list}>
					{suggestions.map((suggestion) => (
						<option key={suggestion} value={suggestion} />
					))}
				</datalist>
			)}
		</>
	);
}
