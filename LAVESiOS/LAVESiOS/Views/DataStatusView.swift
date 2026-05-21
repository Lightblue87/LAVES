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

                if store.isUpdating || store.updateDetail != nil {
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
                        } else if store.isUpdating {
                            ProgressView()
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
