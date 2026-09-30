import { DropArea } from "@/features/drop/DropArea";
import { Drops } from "@/features/drop/Drops";
import styles from "./Home.module.css";

export function Home() {
	return (
		<main className={styles.home}>
			<DropArea />
			<Drops />
		</main>
	);
}
