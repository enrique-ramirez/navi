import type { ReactNode } from "react";

import styles from "./Alert.module.css";

export function Alert({ children }: { children: ReactNode }) {
	return (
		<div role="alert" className={styles.alert}>
			{children}
		</div>
	);
}
