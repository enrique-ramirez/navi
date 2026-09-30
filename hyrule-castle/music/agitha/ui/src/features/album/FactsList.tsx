import styles from "./FactsList.module.css";

export interface Fact {
	name: string;
	value: string;
	path?: boolean;
}

export function FactsList({
	facts,
	compact = false,
}: {
	facts: Fact[];
	compact?: boolean;
}) {
	return (
		<dl
			className={compact ? `${styles.facts} ${styles.compact}` : styles.facts}
		>
			{facts.map(({ name, value, path }) => (
				<div key={name}>
					<dt>{name}</dt>
					<dd className={path ? styles.path : undefined}>{value}</dd>
				</div>
			))}
		</dl>
	);
}
