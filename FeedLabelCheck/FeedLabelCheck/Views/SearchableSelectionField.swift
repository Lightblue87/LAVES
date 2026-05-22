import SwiftUI

struct SearchableSelectionField: View {
    let title: String
    let placeholder: String
    let values: [String]
    @Binding var selection: String

    @State private var isPresented = false

    var body: some View {
        Button {
            isPresented = true
        } label: {
            HStack {
                Text(title)
                    .foregroundStyle(.primary)
                Spacer(minLength: 16)
                Text(selection.isEmpty ? placeholder : selection)
                    .foregroundStyle(selection.isEmpty ? .secondary : .primary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Image(systemName: "chevron.up.chevron.down")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .sheet(isPresented: $isPresented) {
            SearchableSelectionSheet(
                title: title,
                values: values,
                selection: $selection
            )
        }
    }
}

private struct SearchableSelectionSheet: View {
    let title: String
    let values: [String]
    @Binding var selection: String

    @Environment(\.dismiss) private var dismiss
    @State private var query = ""

    private var filteredValues: [String] {
        let trimmedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedQuery.isEmpty else {
            return values
        }
        return values.filter { $0.localizedCaseInsensitiveContains(trimmedQuery) }
    }

    var body: some View {
        NavigationStack {
            List {
                if !selection.isEmpty {
                    Button(role: .destructive) {
                        selection = ""
                        dismiss()
                    } label: {
                        Label("Auswahl löschen", systemImage: "xmark.circle")
                    }
                }

                ForEach(filteredValues, id: \.self) { value in
                    Button {
                        selection = value
                        dismiss()
                    } label: {
                        HStack {
                            Text(value)
                                .foregroundStyle(.primary)
                            Spacer()
                            if value == selection {
                                Image(systemName: "checkmark")
                                    .foregroundStyle(.blue)
                            }
                        }
                    }
                }
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always))
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Fertig") {
                        dismiss()
                    }
                }
            }
        }
    }
}
