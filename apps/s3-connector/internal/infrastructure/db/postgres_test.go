package db

import (
	"context"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/lib/pq"
)

func TestPostgresDB_FindExisting(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatalf("an error '%s' was not expected when opening a stub database connection", err)
	}
	defer db.Close()

	database := &PostgresDB{db: db}
	ctx := context.Background()
	etags := []string{"etag1", "etag2", "etag3"}

	rows := sqlmock.NewRows([]string{"etag"}).
		AddRow("etag1").
		AddRow("etag3")

	mock.ExpectQuery("^SELECT etag FROM processed_documents WHERE etag = ANY\\(\\$1\\)$").
		WithArgs(pq.Array(etags)).
		WillReturnRows(rows)

	existing, err := database.FindExisting(ctx, etags)
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}

	if len(existing) != 2 {
		t.Fatalf("expected 2 existing etags, got %d", len(existing))
	}
	if existing[0] != "etag1" || existing[1] != "etag3" {
		t.Fatalf("unexpected existing etags: %v", existing)
	}

	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("there were unfulfilled expectations: %s", err)
	}
}

func TestPostgresDB_BulkMarkProcessed(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatalf("an error '%s' was not expected when opening a stub database connection", err)
	}
	defer db.Close()

	database := &PostgresDB{db: db}
	ctx := context.Background()
	etags := []string{"etag1", "etag2"}

	mock.ExpectExec("^INSERT INTO processed_documents \\(etag\\) SELECT \\* FROM UNNEST\\(\\$1::text\\[\\]\\) ON CONFLICT DO NOTHING$").
		WithArgs(pq.Array(etags)).
		WillReturnResult(sqlmock.NewResult(0, 2))

	err = database.BulkMarkProcessed(ctx, etags)
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}

	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("there were unfulfilled expectations: %s", err)
	}
}
