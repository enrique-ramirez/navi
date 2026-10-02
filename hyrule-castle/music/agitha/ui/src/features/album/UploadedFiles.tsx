import { Play, Square } from "lucide-react";
import { useState } from "react";

import { uploadedValues } from "@/domain/album/albumTags";
import { describeEncoding } from "@/domain/album/describeEncoding";
import {
	formatKbps,
	formatLength,
	formatSize,
	formatValues,
} from "@/domain/album/format";
import { bytesOf } from "@/domain/album/tagModel";
import { mimeOf, usePlayer } from "@/domain/player/usePlayer";
import type { AlbumView, UploadedFile } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import pageStyles from "@/shared/styles/albumPage.module.css";
import detailStyles from "@/shared/styles/trackDetail.module.css";
import { FactsList } from "@/shared/ui/FactsList";
import listStyles from "@/shared/ui/TrackRows.module.css";
import styles from "./UploadedFiles.module.css";

function Tags({ view, file }: { view: AlbumView; file: UploadedFile }) {
	const { t } = useTranslate();
	const names = view.names[file.family] ?? {};
	const order = Object.keys(names);
	const rank = (key: string) => {
		const at = order.indexOf(key);
		return at === -1 ? order.length : at;
	};
	const keys = Object.keys(file.tags).sort(
		(a, b) => rank(a) - rank(b) || a.localeCompare(b),
	);

	return (
		<table
			className={styles.tags}
			aria-label={t("uploaded.tagsOf", { file: file.path })}
		>
			<thead>
				<tr>
					<th scope="col">{t("tags.tag")}</th>
					<th scope="col">{t("tags.now")}</th>
				</tr>
			</thead>
			<tbody>
				{keys.map((key) => (
					<tr key={key}>
						<th scope="row" title={key}>
							{names[key] ?? key}
						</th>
						<td>
							{formatValues(
								(file.tags[key] ?? []).map((value) => {
									const size = bytesOf(value);
									return size
										? t("tags.binary", { kind: key.split(":")[0] ?? key, size })
										: value;
								}),
							)}
						</td>
					</tr>
				))}
			</tbody>
		</table>
	);
}

export function UploadedFiles({ view }: { view: AlbumView }) {
	const { t } = useTranslate();
	const player = usePlayer();
	const files = view.uploaded ?? [];
	const [selected, setSelected] = useState(0);
	const file = files[selected] ?? files[0];
	if (!file) return null;
	const discs = new Set(files.map((each) => uploadedValues(each).disc));

	return (
		<section className={pageStyles.tracks} aria-labelledby="uploaded-title">
			<div className={pageStyles.trackList}>
				<h2 id="uploaded-title" className={pageStyles.label}>
					{t("uploaded.title", { n: files.length })}
				</h2>
				<p className={styles.note}>{t("uploaded.note")}</p>
				<table className={listStyles.table} aria-label={t("uploaded.list")}>
					<thead>
						<tr>
							<th scope="col">
								<span className="visually-hidden">{t("tracks.player")}</span>
							</th>
							<th scope="col">{t("tracks.number")}</th>
							<th scope="col">{t("tracks.name")}</th>
							<th scope="col" className={listStyles.right}>
								{t("tracks.length")}
							</th>
						</tr>
					</thead>
					<tbody>
						{files.map((each, index) => {
							const values = uploadedValues(each);
							const title =
								values.title || each.path.split("/").pop() || each.path;
							const mime = mimeOf(each.format);
							const playing = player.playing === each.path;
							const number = [discs.size > 1 ? values.disc : "", values.track]
								.filter(Boolean)
								.join("-");
							return (
								<tr
									key={each.path}
									aria-selected={index === selected}
									className={index === selected ? listStyles.selected : ""}
									onClick={() => setSelected(index)}
								>
									<td className={listStyles.number}>
										<button
											type="button"
											className={listStyles.play}
											disabled={!player.canPlay(mime)}
											aria-label={
												player.canPlay(mime)
													? t(playing ? "track.stop" : "track.play", { title })
													: t("track.cantPlay", { format: each.format })
											}
											title={
												player.canPlay(mime)
													? undefined
													: t("track.cantPlay", { format: each.format })
											}
											onClick={(event) => {
												event.stopPropagation();
												if (playing) player.stop();
												else player.play(each.path, each.audio_url, mime);
											}}
										>
											{playing ? (
												<Square size={16} aria-hidden="true" />
											) : (
												<Play size={16} aria-hidden="true" />
											)}
										</button>
									</td>
									<td className={listStyles.number}>{number || "—"}</td>
									<td>
										<button type="button" className={listStyles.name}>
											<span className={listStyles.title}>{title}</span>
											<span className={listStyles.file}>{each.path}</span>
										</button>
									</td>
									<td className={`${listStyles.number} ${listStyles.right}`}>
										{formatLength(each.length)}
									</td>
								</tr>
							);
						})}
					</tbody>
				</table>
			</div>

			<section className={detailStyles.detail} aria-labelledby="uploaded-file">
				<h3 id="uploaded-file" className={detailStyles.title}>
					{uploadedValues(file).title || file.path}
				</h3>
				<div className={detailStyles.group}>
					<h4 className={detailStyles.label}>{t("uploaded.tags")}</h4>
					<Tags view={view} file={file} />
				</div>
				<div className={detailStyles.group}>
					<h4 className={detailStyles.label}>{t("file.title")}</h4>
					<FactsList
						facts={[
							{ name: t("file.format"), value: describeEncoding(file, t) },
							{ name: t("file.bitrate"), value: formatKbps(file.bitrate) },
							{ name: t("file.size"), value: formatSize(file.size) },
							{ name: t("file.pathNow"), value: file.path, path: true },
						]}
					/>
				</div>
			</section>
		</section>
	);
}
