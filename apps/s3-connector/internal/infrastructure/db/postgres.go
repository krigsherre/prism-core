package db

import (
	"context"
	"database/sql"

	"github.com/lib/pq"
)

type PostgresDB struct {
	db *sql.DB
}

func NewPostgresDB(dsn string, maxOpenConns, maxIdleConns int) (*PostgresDB, error) {
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		return nil, err
	}

	db.SetMaxOpenConns(maxOpenConns)
	db.SetMaxIdleConns(maxIdleConns)

	_, err = db.Exec(`
		CREATE TABLE IF NOT EXISTS processed_documents (
			id SERIAL PRIMARY KEY,
			etag TEXT UNIQUE NOT NULL,
			processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		)
	`)
	if err != nil {
		return nil, err
	}

	return &PostgresDB{db: db}, nil
}

func (d *PostgresDB) FindExisting(ctx context.Context, etags []string) ([]string, error) {
	if len(etags) == 0 {
		return nil, nil
	}

	rows, err := d.db.QueryContext(ctx, "SELECT etag FROM processed_documents WHERE etag = ANY($1)", pq.Array(etags))
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var existing []string
	for rows.Next() {
		var etag string
		if err := rows.Scan(&etag); err != nil {
			return nil, err
		}
		existing = append(existing, etag)
	}
	return existing, rows.Err()
}

func (d *PostgresDB) BulkMarkProcessed(ctx context.Context, etags []string) error {
	if len(etags) == 0 {
		return nil
	}

	_, err := d.db.ExecContext(ctx, "INSERT INTO processed_documents (etag) SELECT * FROM UNNEST($1::text[]) ON CONFLICT DO NOTHING", pq.Array(etags))
	return err
}

func (d *PostgresDB) Close() error {
	return d.db.Close()
}
