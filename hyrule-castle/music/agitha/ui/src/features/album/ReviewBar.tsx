import { Link, useNavigate } from "@tanstack/react-router";
import {
	LoaderCircle,
	RefreshCw,
	ScanSearch,
	Trash2,
	Undo2,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { isRunning } from "@/domain/album/albumQuery";
import { albumTags } from "@/domain/album/albumTags";
import type { AlbumView } from "@/shared/api/types";
import { albumStatePhrase } from "@/shared/i18n/albumState";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { Alert } from "@/shared/ui/Alert";
import { Confirm } from "@/shared/ui/Confirm";
import { approveReason } from "./approveReason";
import { Outcome } from "./Outcome";
import type { Draft, Pending } from "./pending";
import styles from "./ReviewBar.module.css";
import { useDecision } from "./useDecision";

const releaseOf = (draft: Draft) =>
	draft.action === "repoint" ? `repoint ${draft.release}` : draft.release_id;

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
	const navigate = useNavigate();
	const [asking, setAsking] = useState(false);
	const {
		refusal,
		changed,
		awaiting,
		busy,
		submit,
		send,
		approve,
		move,
		refresh,
	} = useDecision(view, pending);

	// Another release replans every tag, so it is sent as soon as it is chosen rather than on Save.
	// `sent` keeps a release identify refused from being sent again on every render.
	const release = releaseOf(pending.draft);
	const sent = useRef<string | null>(null);
	// biome-ignore lint/correctness/useExhaustiveDependencies: sends when the chosen release changes, not on every new view
	useEffect(() => {
		if (busy || view.state !== "ready") return;
		if (release === (view.preview?.release_id ?? "")) {
			sent.current = null;
			return;
		}
		if (sent.current === release) return;
		sent.current = release;
		void send({ kind: "preview" });
	}, [release, busy, view.state]);

	const running = isRunning(view.state);
	const tags = albumTags(view);
	const title = tags.title || view.name;

	const duplicateChoice = view.duplicate !== null && view.state === "ready";
	const primary: Primary =
		awaiting !== null
			? awaiting.then.kind === "approve"
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
		awaiting?.then.kind === "approve"
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
		if (primary === "save") void send({ kind: "preview" });
		else if (primary === "confirm") void send({ kind: "approve" });
		else if (primary === "approve") void approve();
		else if (primary === "move") void move();
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
								aria-label={view.busy ? t("actions.discardBusy") : undefined}
								title={view.busy ? t("actions.discardBusy") : undefined}
								onClick={() => setAsking(true)}
							>
								<Trash2 size={14} aria-hidden="true" />
								{t("action.discard")}
							</button>
						)}
						{!busy &&
							view.state === "ready" &&
							!pending.dirty &&
							view.approvable.code === "not-accepted" && (
								<button
									type="button"
									className={styles.ghost}
									onClick={() => void send({ kind: "preview" })}
								>
									<RefreshCw size={14} aria-hidden="true" />
									{t("review.repreview")}
								</button>
							)}
						{!busy && view.state === "ready" && !pending.dirty && (
							<button
								type="button"
								className={styles.ghost}
								title={t("review.reidentifyWhy")}
								onClick={() =>
									void submit("reidentify", {}).then(async (ok) => {
										if (ok) await refresh();
									})
								}
							>
								<ScanSearch size={14} aria-hidden="true" />
								{t("review.reidentify")}
							</button>
						)}
						{primary !== null && (
							<button
								type="button"
								className={styles.primary}
								disabled={busy || blocked !== null}
								aria-label={
									blocked === null
										? undefined
										: t("actions.approveWhy", { why: blocked })
								}
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
				{changed && <Alert>{t("review.changed")}</Alert>}
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
