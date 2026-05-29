import SwiftUI

struct DataStatusView: View {
    @ObservedObject var store: AdditiveStore
    @ObservedObject var labelingStore: LabelingRuleStore
    @ObservedObject var coordinator: AppUpdateCoordinator

    var body: some View {
        NavigationStack {
            Form {
                // ── Zusatzstoffe-Datenbank ───────────────────────────────
                additiveSection

                // ── Kennzeichnungsregeln-Datenbank ───────────────────────
                labelingSection

                // ── Fortschritt während des Updates ─────────────────────
                if coordinator.isUpdating {
                    Section("Aktualisierung läuft") {
                        updateProgressRows
                    }
                }

                // ── Fehlermeldung ────────────────────────────────────────
                if let err = coordinator.updateError {
                    Section {
                        Text(err).foregroundStyle(.red)
                    }
                }

                // ── Zentraler Update-Knopf ───────────────────────────────
                Section {
                    updateButton
                } footer: {
                    Text("Aktualisiert beide Datenbanken in einem Schritt.")
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

            if !store.currentSHA256.isEmpty {
                Section {
                    sha256Row(store.currentSHA256)
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

            if let sha = labelingStore.dbInfo?.sha256, !sha.isEmpty {
                Section {
                    sha256Row(sha)
                }
            }
        }
    }

    // MARK: - Update UI

    @ViewBuilder
    private var updateProgressRows: some View {
        if let d = coordinator.detail {
            Text(d).foregroundStyle(.secondary)
        }
        if let p = coordinator.progress {
            ProgressView(value: p)
            Text("\(Int(p * 100)) %")
                .font(.caption)
                .foregroundStyle(.secondary)
        } else {
            ProgressView()
        }
    }

    private var updateButton: some View {
        Button {
            Task { await coordinator.performUpdate() }
        } label: {
            HStack {
                if coordinator.isUpdating {
                    Label("Aktualisierung läuft…", systemImage: "arrow.down.circle")
                } else if coordinator.updateAvailable {
                    Label("Alles aktualisieren", systemImage: "arrow.down.circle.fill")
                        .foregroundStyle(.blue)
                } else {
                    Label("Auf Aktualisierungen prüfen", systemImage: "arrow.clockwise")
                }
                Spacer()
                if coordinator.updateAvailable && !coordinator.isUpdating {
                    Image(systemName: "exclamationmark.circle.fill")
                        .foregroundStyle(.orange)
                        .imageScale(.small)
                }
            }
        }
        .disabled(coordinator.isUpdating)
    }

    // MARK: - Helpers

    private var labelingStatusText: String {
        if !labelingStore.isLoaded { return "Nicht geladen" }
        if let info = labelingStore.dbInfo { return info.version }
        return "Geladen"
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
}
