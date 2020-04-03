#!/usr/bin/env perl

use strict;
use warnings;

use lib '.';
use Bugzilla;
use Bugzilla::DB::Sqlite;

my $db = Bugzilla::DB::Sqlite->new({
    db_name => 'data/db/bugs',
});

open my $fh, '<', 'bugzilla.sql';

while (<$fh>) {
    chomp;
    next unless $_;
    $db->do($_);
};
