import { ChevronRight, File, Folder as FolderIcon } from "lucide-react";
import type { ReactNode } from "react";

import type { AlbumView } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import styles from "./Landing.module.css";

interface Folder {
	name: string;
	children: Folder[] | null;
}

function nest(paths: string[]): Folder[] {
	const root: Folder[] = [];
	for (const path of paths) {
		const parts = path.split("/");
		let level = root;
		parts.forEach((name, index) => {
			const isFile = index === parts.length - 1;
			let node = level.find((each) => each.name === name);
			if (!node) {
				node = { name, children: isFile ? null : [] };
				level.push(node);
			}
			if (node.children) level = node.children;
		});
	}
	return root;
}

function Tree({ nodes, label }: { nodes: Folder[]; label: string }) {
	return (
		<ul className={styles.tree} aria-label={label}>
			{nodes.map((node) => (
				<li key={node.name}>
					{node.children ? (
						<FolderIcon size={14} aria-hidden="true" />
					) : (
						<File size={14} aria-hidden="true" />
					)}
					<span>{node.name}</span>
					{node.children && <Tree nodes={node.children} label={node.name} />}
				</li>
			))}
		</ul>
	);
}

function Disclosure({
	summary,
	children,
}: {
	summary: string;
	children: ReactNode;
}) {
	return (
		<details className={styles.details}>
			<summary>
				<ChevronRight size={14} aria-hidden="true" className={styles.chevron} />
				{summary}
			</summary>
			{children}
		</details>
	);
}

export function Landing({ view }: { view: AlbumView }) {
	const { t } = useTranslate();
	const preview = view.preview;
	if (preview === null) return null;

	return (
		<section className={styles.landing} aria-labelledby="landing-title">
			<h3 id="landing-title" className={styles.label}>
				{t("landing.title")}
			</h3>
			{preview.destination ? (
				<p className={styles.path} title={view.library_path ?? undefined}>
					{preview.destination}
				</p>
			) : (
				<p className={styles.muted}>{t("landing.noDestination")}</p>
			)}

			<Disclosure summary={t("landing.folderCount", { n: view.tree.length })}>
				<Tree nodes={nest(view.tree)} label={t("landing.folder")} />
			</Disclosure>

			{preview.deletions.length > 0 && (
				<Disclosure
					summary={t("landing.deletedCount", { n: preview.deletions.length })}
				>
					<ul className={styles.plain} aria-label={t("landing.deleted")}>
						{preview.deletions.map((path) => (
							<li key={path}>{path.split("/").pop()}</li>
						))}
					</ul>
				</Disclosure>
			)}

			{view.extras_to.length > 0 && (
				<Disclosure
					summary={t("landing.extrasCount", { n: view.extras_to.length })}
				>
					<ul className={styles.plain} aria-label={t("landing.extras")}>
						{view.extras_to.map((extra) => (
							<li key={extra.source}>
								<span>{extra.source}</span>{" "}
								<span className={styles.muted}>{t("landing.goesTo")}</span>{" "}
								<span className={styles.path}>{extra.path}</span>
							</li>
						))}
					</ul>
				</Disclosure>
			)}
		</section>
	);
}
