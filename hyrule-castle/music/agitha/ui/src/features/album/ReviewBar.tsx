import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { LoaderCircle, Trash2, Undo2 } from "lucide-react";
import { useEffect, useState } from "react";
import { albumKey, isRunning } from "@/domain/album/albumQuery";
import { albumTags } from "@/domain/album/albumTags";
import { albumUrl, post } from "@/shared/api/album";
import type { AlbumView } from "@/shared/api/types";
import { albumStatePhrase } from "@/shared/i18n/albumState";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { Alert } from "@/shared/ui/Alert";
import { Confirm } from "@/shared/ui/Confirm";
import { approveReason } from "./approveReason";
import { Outcome } from "./Outcome";
import type { Pending } from "./pending";
import styles from "./ReviewBar.module.css";

// What the primary button does. `confirm` sends the unchanged draft so the server accepts the
// preview, then approves once identify has run again; `save` sends the owner's changes and stops,
// so the new preview can be looked at before approving.
type Primary = "approve" | "confirm" | "save" | "move" | null;

export function ReviewBar({
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
	const [asking, setAsking] = useState(false);
	// Set from sending a decision until identify has answered it; `approve` approves then.
	// `seen` records that the view has shown identify running, since the view arrives from the
	// parent's query a render later than this state changes.
	const [awaiting, setAwaiting] = useState<{
		then: "preview" | "approve";
		seen: boolean;
	} | null>(null);

	const running = isRunning(view.state);
	const refresh = () => client.invalidateQueries({ queryKey: albumKey(view) });
	const tags = albumTags(view);
	const title = tags.title || view.name;

	async function submit(path: string, body: unknown) {
		setRefusal(null);
		setSending(true);
		const answer = await post(`${albumUrl(view)}/${path}`, body);
		setSending(false);
		if (!answer.ok) setRefusal(answer.error);
		return answer.ok;
	}

	async function send(then: "preview" | "approve") {
		if (!(await submit("decision", pending.draft))) return;
		setAwaiting({ then, seen: false });
		await refresh();
	}

	async function act(path: "approve" | "move") {
		if (await submit(path, {})) await refresh();
	}

	// Identify has answered the sent decision: a message keeps the draft, none settles it.
	// biome-ignore lint/correctness/useExhaustiveDependencies: runs when identify finishes, not when the view's other fields change
	useEffect(() => {
		if (awaiting === null) return;
		if (running) {
			if (!awaiting.seen) setAwaiting({ ...awaiting, seen: true });
			return;
		}
		// Identify can finish before a poll sees it run: the view then already holds the sent
		// decision and a preview planned under it.
		const answered =
			awaiting.seen ||
			(view.decision !== null &&
				!pending.dirty &&
				(view.approvable.code !== "not-accepted" || view.error !== null));
		if (!answered) return;
		setAwaiting(null);
		if (view.error) return;
		pending.reset();
		if (awaiting.then === "approve" && view.approvable.ok && !view.duplicate)
			void act("approve");
	}, [awaiting, running, view]);

	const busy = running || sending || awaiting !== null;
	const duplicateChoice = view.duplicate !== null && view.state === "ready";
	const primary: Primary =
		awaiting !== null
			? awaiting.then === "approve"
				? "confirm"
				: "save"
			: view.state === "written, not moved"
				? "move"
				: view.state !== "ready" || duplicateChoice
					? null
					: pending.dirty
						? "save"
						: view.approvable.code === "not-accepted"
							? "confirm"
							: "approve";
	const blocked =
		primary === "approve" && !view.approvable.ok
			? approveReason(view, t)
			: null;

	const progress =
		awaiting?.then === "approve"
			? t("review.approving")
			: awaiting !== null || running
				? t(albumStatePhrase[view.state])
				: null;

	const labels: Record<Exclude<Primary, null>, string> = {
		approve: t("actions.approve"),
		confirm: t("actions.approve"),
		save: t("review.save"),
		move: t("action.moveIntoLibrary"),
	};

	function press() {
		if (primary === "save") void send("preview");
		else if (primary === "confirm") void send("approve");
		else if (primary === "approve") void act("approve");
		else if (primary === "move") void act("move");
	}

	// The server keeps identify's refusal in `error`; it shows once no answer is awaited.
	const message =
		refusal ??
		(awaiting === null && view.state === "ready" ? view.error : null);

	return (
		<>
			<div className={styles.bar}>
				<div className={styles.inner}>
					<div className={styles.where}>
						<Link to="/" className={styles.crumb}>
							{t("review.drop", { drop: view.drop, n: view.n })}
						</Link>
						<div className={styles.titleLine}>
							<h1 className={styles.title}>{title}</h1>
							<span className={styles.badge} data-state={view.state}>
								{running && (
									<LoaderCircle
										size={12}
										className={styles.spin}
										aria-hidden="true"
									/>
								)}
								{t(albumStatePhrase[view.state])}
							</span>
						</div>
					</div>

					<div className={styles.actions}>
						{pending.dirty && !busy && (
							<>
								<span className={styles.unsaved}>{t("review.unsaved")}</span>
								<button
									type="button"
									className={styles.ghost}
									onClick={() => pending.reset()}
								>
									<Undo2 size={14} aria-hidden="true" />
									{t("review.undo")}
								</button>
							</>
						)}
						{view.state !== "in the library" && (
							<button
								type="button"
								className={styles.danger}
								disabled={view.busy || busy}
								title={view.busy ? t("actions.discardBusy") : undefined}
								onClick={() => setAsking(true)}
							>
								<Trash2 size={14} aria-hidden="true" />
								{t("action.discard")}
							</button>
						)}
						{primary !== null && (
							<button
								type="button"
								className={styles.primary}
								disabled={busy || blocked !== null}
								title={blocked ?? undefined}
								onClick={press}
							>
								{busy && (
									<LoaderCircle
										size={14}
										className={styles.spin}
										aria-hidden="true"
									/>
								)}
								{progress ?? labels[primary]}
							</button>
						)}
						{duplicateChoice && (
							<span className={styles.note}>{t("review.chooseCopy")}</span>
						)}
					</div>
				</div>
				{blocked && (
					<p className={styles.blocked}>
						{t("actions.approveWhy", { why: blocked })}
					</p>
				)}
			</div>

			<div className={styles.messages}>
				<Outcome view={view} />
				{message && <Alert>{message}</Alert>}
			</div>

			{asking && (
				<Confirm
					message={t("confirm.discardAlbum", { title })}
					confirmLabel={t("action.discard")}
					onCancel={() => setAsking(false)}
					onConfirm={() => {
						setAsking(false);
						void submit("discard", {}).then(async (ok) => {
							if (ok) await navigate({ to: "/" });
						});
					}}
				/>
			)}
		</>
	);
}
