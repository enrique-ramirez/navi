import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { type ReactNode, useState } from "react";

import { albumKey, albumQuery } from "@/domain/album/albumQuery";
import {
	formatKbps,
	formatKilohertz,
	formatSize,
	formatTotalLength,
} from "@/domain/album/format";
import { albumUrl, post } from "@/shared/api/album";
import type { AlbumView, Comparison, Copy, CopySide } from "@/shared/api/types";
import type { Phrase } from "@/shared/i18n/en";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { Alert } from "@/shared/ui/Alert";
import { approveReason } from "./approveReason";
import styles from "./Duplicate.module.css";
import { Outcome } from "./Outcome";
import type { Pending } from "./pending";

// Criterion 48's rules, by the code the server sends.
const RULES: Record<Comparison["rule_code"], Phrase> = {
	"more-files": "rule.moreFiles",
	lossless: "rule.lossless",
	"bit-depth": "rule.bitDepth",
	"sample-rate": "rule.sampleRate",
	bitrate: "rule.bitrate",
	library: "rule.library",
};

export function Duplicate({
	view,
	pending,
}: {
	view: AlbumView;
	pending: Pending;
}) {
	const { t } = useTranslate();
	const client = useQueryClient();
	const navigate = useNavigate();
	const [refusal, setRefusal] = useState<string | null>(null);
	const [sending, setSending] = useState(false);
	// The same query as the album page, so a poll here also updates the page.
	const { data: current } = useQuery({
		...albumQuery(view.drop, view.n),
		initialData: view,
	});
	const { duplicate } = current;

	async function keep(side: CopySide) {
		setRefusal(null);
		setSending(true);
		const answer = await post(`${albumUrl(current)}/approve`, { keep: side });
		setSending(false);
		if (!answer.ok) setRefusal(answer.error);
		else if (side === "library") await navigate({ to: "/" });
		else await client.invalidateQueries({ queryKey: albumKey(view) });
	}

	// What stops both buttons: a running process, an unsent change, or the album not being approvable.
	const why = current.busy
		? t("duplicate.running")
		: pending.dirty
			? t("actions.updateFirst")
			: approveReason(current, t);
	const disabled = why !== null || sending;
	const label = (phrase: "duplicate.keepNew" | "duplicate.keepLibrary") =>
		why === null
			? t(phrase)
			: t("duplicate.keepWhy", { action: t(phrase), why });

	const facts: [string, (copy: Copy, side: CopySide) => ReactNode][] = [
		[t("duplicate.folder"), (copy) => copy.folder],
		[t("file.format"), (copy) => copy.format],
		[
			t("duplicate.lossless"),
			(copy) => t(copy.lossless ? "file.lossless" : "file.lossy"),
		],
		[
			t("duplicate.bitDepth"),
			(copy) =>
				copy.bit_depth === null
					? t("duplicate.none")
					: t("file.bitDepth", { n: copy.bit_depth }),
		],
		[t("duplicate.sampleRate"), (copy) => formatKilohertz(copy.sample_rate)],
		[t("duplicate.bitrate"), (copy) => formatKbps(copy.bitrate)],
		[t("duplicate.files"), (copy) => copy.files],
		[t("duplicate.length"), (copy) => formatTotalLength(copy.length)],
		[t("duplicate.size"), (copy) => formatSize(copy.size)],
		[
			t("duplicate.cover"),
			(copy, side) =>
				copy.cover ? (
					<>
						<img
							src={copy.cover.url}
							alt={t("duplicate.coverAlt", {
								side: t(side === "new" ? "duplicate.new" : "duplicate.library"),
								w: copy.cover.width,
								h: copy.cover.height,
							})}
							className={styles.cover}
						/>
						<span>
							{t("duplicate.by", { w: copy.cover.width, h: copy.cover.height })}
						</span>
					</>
				) : (
					t("duplicate.noCover")
				),
		],
	];

	return (
		<section className={styles.duplicate} aria-labelledby="duplicate-title">
			<h2 id="duplicate-title">{t("duplicate.title")}</h2>
			{duplicate && (
				<>
					<table
						className={styles.table}
						aria-label={t("duplicate.comparison")}
					>
						<thead>
							<tr>
								<th scope="col">
									<span className="visually-hidden">{t("duplicate.fact")}</span>
								</th>
								{(["new", "library"] as const).map((side) => (
									<th key={side} scope="col">
										{t(
											side === "new"
												? "duplicate.new"
												: "duplicate.libraryCopy",
										)}
										{duplicate.recommended === side && (
											<span className={styles.recommended}>
												{" "}
												{t("duplicate.recommendedMark")}
											</span>
										)}
									</th>
								))}
							</tr>
						</thead>
						<tbody>
							{facts.map(([name, show]) => (
								<tr key={name}>
									<th scope="row">{name}</th>
									<td>{show(duplicate.new, "new")}</td>
									<td>{show(duplicate.library, "library")}</td>
								</tr>
							))}
						</tbody>
					</table>
					<p role="status" className={styles.recommendation}>
						{t("duplicate.recommended", {
							which: t(
								duplicate.recommended === "new"
									? "duplicate.theNew"
									: "duplicate.theLibrary",
							),
							rule: t(RULES[duplicate.rule_code]),
						})}
					</p>
					<div className={styles.buttons}>
						<button
							type="button"
							className={styles.button}
							disabled={disabled}
							onClick={() => void keep("new")}
						>
							{label("duplicate.keepNew")}
						</button>
						<button
							type="button"
							className={styles.button}
							disabled={disabled}
							onClick={() => void keep("library")}
						>
							{label("duplicate.keepLibrary")}
						</button>
					</div>
				</>
			)}
			<Outcome view={current} />
			{refusal && <Alert>{refusal}</Alert>}
		</section>
	);
}
