import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { albumQuery } from "@/domain/album/albumQuery";
import {
	formatKbps,
	formatKilohertz,
	formatSize,
	formatTotalLength,
} from "@/domain/album/format";
import type { AlbumView, Comparison, Copy, CopySide } from "@/shared/api/types";
import type { Phrase } from "@/shared/i18n/en";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { Alert } from "@/shared/ui/Alert";
import { approveReason } from "./approveReason";
import styles from "./Duplicate.module.css";
import { Outcome } from "./Outcome";
import type { Pending } from "./pending";
import { useDecision } from "./useDecision";

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
	const navigate = useNavigate();
	// The same query as the album page, so this panel keeps polling where it is shown alone.
	const { data: current } = useQuery({
		...albumQuery(view.drop, view.n),
		initialData: view,
	});
	const { refusal, changed, awaiting, busy, send, approve } = useDecision(
		current,
		pending,
	);
	const { duplicate } = current;

	// Keeping the library's copy discards the upload and needs no accepted preview. Keeping the
	// new one approves it, so a preview not accepted yet is accepted first, as Approve does.
	async function keep(side: CopySide) {
		if (side === "library") {
			if (await approve("library")) await navigate({ to: "/" });
		} else if (current.approvable.code === "not-accepted") {
			await send({ kind: "approve", keep: "new" });
		} else {
			await approve("new");
		}
	}

	// What stops the buttons: a running process, an unsent change, or, for the new copy, a hold.
	const stopped = current.busy
		? t("duplicate.running")
		: pending.dirty
			? t("actions.updateFirst")
			: null;
	const why: Record<CopySide, string | null> = {
		library: stopped,
		new:
			stopped ??
			(current.approvable.code === "not-accepted"
				? null
				: approveReason(current, t)),
	};
	const label = (side: CopySide) => {
		const phrase =
			side === "new" ? "duplicate.keepNew" : "duplicate.keepLibrary";
		if (awaiting?.then.kind === "approve" && side === "new")
			return t("review.approving");
		const reason = why[side];
		return reason === null
			? t(phrase)
			: t("duplicate.keepWhy", { action: t(phrase), why: reason });
	};

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
							data-recommended={duplicate.recommended === "new" || undefined}
							disabled={busy || why.new !== null}
							onClick={() => void keep("new")}
						>
							{label("new")}
						</button>
						<button
							type="button"
							className={styles.button}
							data-recommended={
								duplicate.recommended === "library" || undefined
							}
							disabled={busy || why.library !== null}
							onClick={() => void keep("library")}
						>
							{label("library")}
						</button>
					</div>
				</>
			)}
			<Outcome view={current} />
			{refusal && <Alert>{refusal}</Alert>}
			{changed && <Alert>{t("review.changed")}</Alert>}
		</section>
	);
}
