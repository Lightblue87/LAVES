import SwiftUI

struct DataStatusView: View {
    @ObservedObject var store: AdditiveStore

    var body: some View {
        NavigationStack {
            Form {
                Section("Datenbestand") {
                    LabeledContent("Status", value: store.dataStatus)
                    LabeledContent("Datensätze", value: "\(store.additives.count)")
                }

                if let loadError = store.loadError {
                    Section {
                        Text(loadError)
                            .foregroundStyle(.red)
                    }
                }

                if store.isUpdating {
                    Section("Aktualisierung") {
                        if let detail = store.updateDetail {
                            Text(detail)
                                .foregroundStyle(.secondary)
                        }

                        if let progress = store.updateProgress {
                            ProgressView(value: progress)
                            Text("\(Int(progress * 100)) %")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        } else {
                            ProgressView()
                        }
                    }
                }

                if store.updateAvailable {
                    Section {
                        Label("Neue Datenbankversion verfügbar", systemImage: "arrow.down.circle.fill")
                            .foregroundStyle(.blue)
                    }
                }

                if !store.currentSHA256.isEmpty {
                    Section("Integrität") {
                        LabeledContent("SHA-256") {
                            Text(String(store.currentSHA256.prefix(16)) + "…")
                                .font(.caption)
                                .fontDesign(.monospaced)
                                .foregroundStyle(.secondary)
                        }
                        .contextMenu {
                            Button {
                                UIPasteboard.general.string = store.currentSHA256
                            } label: {
                                Label("SHA-256 kopieren", systemImage: "doc.on.doc")
                            }
                        }
                    }
                }

                Section {
                    Button {
                        Task {
                            await store.updateFromRemote()
                        }
                    } label: {
                        if store.isUpdating {
                            Label("Aktualisierung läuft", systemImage: "arrow.down.circle")
                        } else {
                            Label("Daten aktualisieren", systemImage: "arrow.clockwise")
                        }
                    }
                    .disabled(store.isUpdating)
                }
            }
            .navigationTitle("Daten")
        }
    }
}
