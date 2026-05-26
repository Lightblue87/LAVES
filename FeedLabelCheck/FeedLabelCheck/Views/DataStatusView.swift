import SwiftUI

struct DataStatusView: View {
    @ObservedObject var store: AdditiveStore
    @ObservedObject var labelingStore: LabelingRuleStore

    var body: some View {
        NavigationStack {
            Form {

                // ── Zusatzstoffe-Datenbank ───────────────────────────────
                additiveSection

                // ── Kennzeichnungsregeln-Datenbank ───────────────────────
                labelingSection

                // ── Alles auf einmal aktualisieren ───────────────────────
                if store.updateAvailable || labelingStore.updateAvailable {
                    Section {
                        Button {
                            Task {
                                async let a: () = store.updateFromRemote()
                                async let b: () = labelingStore.updateFromRemote()
                                _ = await (a, b)
                            }
                        } label: {
                            Label("Alles aktualisieren", systemImage: "arrow.clockwise.circle.fill")
                                .foregroundStyle(.blue)
                        }
                        .disabled(store.isUpdating || labelingStore.isUpdating)
                    } footer: {
                        Text("Aktualisiert beide Datenbanken gleichzeitig.")
                    }
                }
            }
            .navigationTitle("Daten")
        }
    }

    // MARK: - Zusatzstoffe

    private var additiveSection: some View {
        Group {
            Section("Zusatzstoffe-Datenbank") {
                LabeledContent("Status", value: store.dataStatus)
                LabeledContent("Datensätze", value: "\(store.additives.count)")
            }

            if let err = store.loadError {
                Section {
                    Text(err).foregroundStyle(.red)
                }
            }

            if store.isUpdating {
                Section("Aktualisierung – Zusatzstoffe") {
                    updateProgressRow(detail: store.updateDetail, progress: store.updateProgress)
                }
            }

            if !store.currentSHA256.isEmpty {
                Section {
                    sha256Row(store.currentSHA256)
                }
            }

            Section {
                updateButton(
                    label: "Zusatzstoffe aktualisieren",
                    isUpdating: store.isUpdating,
                    updateAvailable: store.updateAvailable
                ) {
                    Task { await store.updateFromRemote() }
                }
            }
        }
    }

    // MARK: - Kennzeichnungsregeln

    private var labelingSection: some View {
        Group {
            Section("Kennzeichnungsregeln-Datenbank") {
                LabeledContent("Status") {
                    Text(labelingStatusText)
                        .foregroundStyle(labelingStore.isLoaded ? .primary : .secondary)
                }
                if let info = labelingStore.dbInfo {
                    LabeledContent("Regeln", value: "\(info.totalRuleCount)")
                    LabeledContent("Version", value: info.version)
                    LabeledContent("Rechtsgrundlage", value: info.regulation)
                }
                LabeledContent("Futtermitteltypen", value: "\(labelingStore.feedTypes.count)")
                LabeledContent("Futtermittel (VO 68/2013)", value: "\(labelingStore.feedMaterials.count)")
            }

            if let err = labelingStore.loadError {
                Section {
                    Text(err).foregroundStyle(.red)
                }
            }

            if labelingStore.isUpdating {
                Section("Aktualisierung – Kennzeichnungsregeln") {
                    updateProgressRow(detail: labelingStore.updateDetail,
                                      progress: labelingStore.updateProgress)
                }
            }

            if let sha = labelingStore.dbInfo?.sha256, !sha.isEmpty {
                Section {
                    sha256Row(sha)
                }
            }

            Section {
                updateButton(
                    label: "Kennzeichnungsregeln aktualisieren",
                    isUpdating: labelingStore.isUpdating,
                    updateAvailable: labelingStore.updateAvailable
                ) {
                    Task { await labelingStore.updateFromRemote() }
                }
            }
        }
    }

    // MARK: - Shared helpers

    private var labelingStatusText: String {
        if !labelingStore.isLoaded { return "Nicht geladen" }
        if let info = labelingStore.dbInfo { return info.version }
        return "Geladen"
    }

    @ViewBuilder
    private func updateProgressRow(detail: String?, progress: Double?) -> some View {
        if let detail {
            Text(detail)
                .foregroundStyle(.secondary)
        }
        if let progress {
            ProgressView(value: progress)
            Text("\(Int(progress * 100)) %")
                .font(.caption)
                .foregroundStyle(.secondary)
        } else {
            ProgressView()
        }
    }

    @ViewBuilder
    private func sha256Row(_ sha: String) -> some View {
        LabeledContent("SHA-256") {
            Text(String(sha.prefix(16)) + "…")
                .font(.caption)
                .fontDesign(.monospaced)
                .foregroundStyle(.secondary)
        }
        .contextMenu {
            Button {
                UIPasteboard.general.string = sha
            } label: {
                Label("SHA-256 kopieren", systemImage: "doc.on.doc")
            }
        }
    }

    @ViewBuilder
    private func updateButton(
        label: String,
        isUpdating: Bool,
        updateAvailable: Bool,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack {
                if isUpdating {
                    Label("Aktualisierung läuft…", systemImage: "arrow.down.circle")
                } else if updateAvailable {
                    Label(label, systemImage: "arrow.down.circle.fill")
                        .foregroundStyle(.blue)
                } else {
                    Label(label, systemImage: "arrow.clockwise")
                }
                Spacer()
                if updateAvailable && !isUpdating {
                    Image(systemName: "exclamationmark.circle.fill")
                        .foregroundStyle(.orange)
                        .imageScale(.small)
                }
            }
        }
        .disabled(isUpdating)
    }
}
