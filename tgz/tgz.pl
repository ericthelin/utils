#!/usr/bin/perl

$| = 1;

use strict;
use Cwd;
use Cwd 'abs_path';
use File::Basename;
use File::Spec;
use File::Temp qw/ tempdir /;

my %type_handler;

$type_handler{'tar'}     = 'tar -xvf';
$type_handler{'bz2'}     = 'bunzip2 -d';
$type_handler{'gz'}      = 'gunzip -d';
$type_handler{'tar.gz'}  = 'tar --gzip -xvf';
$type_handler{'tar.bz2'} = 'tar --bzip2 -xvf';
$type_handler{'tar.xz'}  = 'tar --xz -xvf';
$type_handler{'gz'}      = 'gunzip -d';
$type_handler{'zip'}     = 'unzip';
$type_handler{'rar'}     = 'unrar x';
$type_handler{'7zip'}    = '7z x';
$type_handler{'xz'}      = 'unxz';
$type_handler{'jar'}     = 'jar -xf';

sub find_type {
    my $file_name = shift;

    my $type;
    my $file = `file -b \"$file_name\"`;

    # print "--------------------------------\n";
    # print "x=$x\n";
    # print "file=$file\n";

    if    ( $file =~ /GNU tar archive/ )    { $type = "tar"; }
    elsif ( $file =~ /tar archive/ )        { $type = "tar"; }
    elsif ( $file =~ /Zip archive data/ )   { $type = "zip"; }
    elsif ( $file =~ /RAR archive data/ )   { $type = "rar"; }
    elsif ( $file =~ /Java Jar file data/ ) { $type = "jar"; }
    elsif ( $file =~ /gzip compressed/ ) {
        if   ( $file_name =~ /\.(tar|tgz)/i || $file =~ /original filename.*\.tar/i ) { $type = "tar.gz"; }
        else                                                                          { $type = "gz"; }
    } elsif ( $file =~ /bzip2 compressed/ ) {
        if   ( $file_name =~ /\.tar/i || $file =~ /original filename.*\.tar/i ) { $type = "tar.bz2"; }
        else                                                                    { $type = "bz2"; }
    } elsif ( $file =~ /XZ compressed/ ) {
        if   ( $file_name =~ /\.(tar|txz)/i || $file =~ /original filename.*\.tar/i ) { $type = "tar.xz"; }
        else                                                                          { $type = "xz"; }
    } elsif ( $file =~ /7-zip archive/i ) {
        $type = "7zip";
    } elsif ( $file_name =~ /\.tar$/i ) {
        $type = "tar";
    } elsif ( $file_name =~ /\.tar.gz$/i ) {
        $type = "tar.gz";
    } elsif ( $file_name =~ /\.tar.bz2$/i ) {
        $type = "tar.bz2";
    } elsif ( $file_name =~ /\.tar.xz$/i ) {
        $type = "tar.xz";
    } elsif ( $file_name =~ /\.bz2/i ) {
        $type = "bz2";
    } elsif ( $file_name =~ /\.gz$/i ) {
        $type = "gz";
    } elsif ( $file_name =~ /\.xz/i ) {
        $type = "xz";
    } elsif ( $file_name =~ /\.zip$/i ) {
        $type = "zip";
    } elsif ( $file_name =~ /\.apk$/i ) {
        $type = "jar";
    } elsif ( $file_name =~ /\.jar$/i ) {
        $type = "jar";
    } elsif ( $file_name =~ /\.7z$/i ) {
        $type = "7zip";
    } else {
        print "unable to find type for '$file_name', skipping it.\n";
    }
    return $type;
}

foreach my $file (@ARGV) {
    my $basename  = basename($file);
    my $fullpath  = abs_path($file);
    my $orig_dir  = getcwd();
    my $orig_file = $file;
    $file     =~ s/\"/\\\"/g;
    $fullpath =~ s/\"/\\\"/g;

    `which aunpack`;
    if ( !$? ) {
        system "aunpack -x \"$file\" 2>&1";
    } else {
        my ( $in, $out ) = '';

        my $type = find_type($file);
        next unless defined $type;

        my ($tempdir) = tempdir('tgz_XXXXXXX');

        # print "tempdir = $tempdir\n";
        chdir($tempdir);
        if ( $type =~ /^(gz|bz2|xz)$/ ) {
            ( my $single = $basename ) =~ s/\.(gz|bz2|xz)$//i;
            $single .= '_extracted' if $single eq $basename;
            system $type_handler{$type} . " -c \"$fullpath\" > \"$single\"";
        } else {
            system $type_handler{$type} . " \"$fullpath\" 2>&1";
        }
        chdir('..');
        opendir( DIR, $tempdir );
        my (@extracted) = grep /^[^.]+/, readdir(DIR);
        closedir DIR;

        # use Data::Dumper; warn Dumper(\@extracted); # EKT
        # use Data::Dumper; warn "count=".scalar(@extracted); # EKT

        # this should be updated to keep trying to find a new name when the one we want is taken
        if ( scalar(@extracted) > 1 ) {
            $in = $tempdir;
            my $out_dir = $basename;
            if ( $out_dir =~ /\.(tar|zip|rar|tar\.gz|tgz|tar\.bz2|bz2|7zip)$/ ) {
                $out_dir =~ s/\.(tar|zip|rar|tar\.gz|tgz|tar\.bz2|bz2|7zip)$//;
            } else {
                $out_dir .= '_extracted';
            }

            $out = get_output_dir($out_dir);
        } else {
            $in  = $tempdir . "/" . $extracted[0];
            $out = get_output_dir( $extracted[0] );
        }

        # use Data::Dumper; warn Dumper($in); # EKT
        # use Data::Dumper; warn Dumper($out); # EKT
        # exit;

        `mv \"$in\" \"$out\"`;

        my ($out_type) = `file -b \"$out\"`;
        chomp($out_type);
        print "extracted to $out ($out_type)\n";
        rmdir($tempdir);

    }
}

sub get_output_dir {
    my $file = shift;

    if ( -e $file ) {
        my $offset = 1;
        while ( -e $file . '_' . sprintf( '%02d', $offset ) ) {
            $offset++;
        }
        return $file . '_' . sprintf( '%02d', $offset );
    }

    return $file;
}
