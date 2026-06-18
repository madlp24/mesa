from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from sales.importers import get_importer_for, persist


class Command(BaseCommand):
    help = "Import sales from a POS report file (Excel, PDF, etc.)."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Path to the report file")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        try:
            importer = get_importer_for(path)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        canonical = importer.normalize(path)
        result = persist(canonical)
        skipped_rows = getattr(importer, "skipped_rows", 0)
        self.stdout.write(
            self.style.SUCCESS(
                f"{result['new']} sales imported, "
                f"{result['items']} items, "
                f"{skipped_rows} rows skipped"
            )
        )
        self.stdout.write(
            f"{result['new']} new sales, "
            f"{result['skipped_duplicate']} skipped as duplicate"
        )
