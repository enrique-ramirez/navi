import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { albumKey, isRunning } from "@/domain/album/albumQuery";
import { albumUrl, post } from "@/shared/api/album";
import type { AlbumView, GameChoice } from "@/shared/api/types";
import { albumStatePhrase } from "@/shared/i18n/albumState";
import type { Phrase } from "@/shared/i18n/en";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { Alert } from "@/shared/ui/Alert";
import styles from "./AlbumActions.module.css";
import { approveReason } from "./approveReason";
import { Outcome } from "./Outcome";
import type { Pending } from "./pending";

const CHOICES: { value: GameChoice; label: Phrase }[] = [
	{ value: "video game music", label: "actions.gameMusic" },
	{ value: "soundtrack", label: "actions.soundtrack.choice" },
	{ value: "neither", label: "actions.neither" },
];

export function AlbumActions({
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
	const [stage, setStage] = useState<"idle" | "waiting" | "running">("idle");

	const running = isRunning(view.state);
	const draft = pending.draft;
	const refresh = () => client.invalidateQueries({ queryKey: albumKey(view) });

	// Identify's answer to a posted decision: a message keeps the draft, none settles it.
	// Until a running state is seen, a stale `ready` settles only once the view holds the draft.
	useEffect(() => {
		if (stage === "waiting" && running) setStage("running");
		else if (
			!running &&
			(stage === "running" || (stage === "waiting" && !pending.dirty))
		) {
			setStage("idle");
			if (!view.error) pending.reset();
		}
	}, [stage, running, view.error, pending]);

	async function submit(
		path: string,
		body: unknown,
		then: () => Promise<void>,
	) {
		setRefusal(null);
		setSending(true);
		const answer = await post(`${albumUrl(view)}/${path}`, body);
		setSending(false);
		if (answer.ok) await then();
		else setRefusal(answer.error);
	}

	const send = () =>
		submit("decision", draft, async () => {
			setStage("waiting");
			await refresh();
		});
	const act = (path: "approve" | "move") => submit(path, {}, refresh);
	const discard = () => submit("discard", {}, () => navigate({ to: "/" }));

	if (view.state === "in the library") {
		return (
			<section className={styles.actions} aria-label={t("actions.title")}>
				<Outcome view={view} />
			</section>
		);
	}

	const blocker = pending.dirty
		? t("actions.updateFirst")
		: (approveReason(view, t) ??
			(view.state !== "ready" ? t(albumStatePhrase[view.state]) : null));
	const approveName =
		blocker === null
			? t("actions.approve")
			: t("actions.approveWhy", { why: blocker });
	const canApprove =
		!pending.dirty &&
		view.approvable.ok &&
		view.state === "ready" &&
		!view.duplicate &&
		!sending;
	const canMove = view.state === "written, not moved";
	// The server keeps identify's refusal in `error`; it is shown only once a fresh answer is in.
	const message =
		refusal ?? (stage === "idle" && view.state === "ready" ? view.error : null);

	return (
		<section className={styles.actions} aria-label={t("actions.title")}>
			{view.preview?.game_choice && (
				<div
					role="radiogroup"
					aria-label={t("actions.soundtrack")}
					className={styles.choices}
				>
					{CHOICES.map(({ value, label }) => (
						<label key={value} className={styles.choice}>
							<input
								type="radio"
								name="soundtrack"
								checked={draft.action === "accept" && draft.game === value}
								onChange={() => pending.setGame(value)}
							/>
							{t(label)}
						</label>
					))}
				</div>
			)}
			<div className={styles.buttons}>
				<button
					type="button"
					className={styles.button}
					disabled={running || sending}
					onClick={() => void send()}
				>
					{running
						? t("actions.updateRunning", { state: view.state })
						: t("actions.update")}
				</button>
				{!view.duplicate && (
					<button
						type="button"
						className={styles.primary}
						disabled={!canApprove}
						onClick={() => void act("approve")}
					>
						{approveName}
					</button>
				)}
				{canMove && (
					<button
						type="button"
						className={styles.button}
						disabled={running || sending}
						onClick={() => void act("move")}
					>
						{t("action.moveIntoLibrary")}
					</button>
				)}
				<button
					type="button"
					className={styles.button}
					disabled={view.busy}
					onClick={() => void discard()}
				>
					{view.busy ? t("actions.discardBusy") : t("action.discard")}
				</button>
			</div>
			<Outcome view={view} />
			{message && <Alert>{message}</Alert>}
		</section>
	);
}
