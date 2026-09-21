#!/usr/bin/perl

use strict;
use warnings;
use Data::Dumper;
use Getopt::Long;
use File::Basename;
use JSON::XS;
use Cwd 'abs_path';
use Term::ANSIColor;

my %options;
Getopt::Long::Configure("gnu_getopt");
GetOptions(
    'help|h'         => \$options{help},
    'replace|R'      => \$options{replace},
    'force|f'        => \$options{force},
    'nice|N'         => \$options{nice},
    'high_quality|H' => \$options{high_quality},
    'preset|p=s'     => \$options{preset},
    'handbrake|b=s'  => \$options{handbrake},
    'output|o=s'     => \$options{output},
    'client|c'       => \$options{client},
    'worker|w'       => \$options{worker},
    'gearman|g=s'    => \$options{gearman},
    'retry|r=i'      => \$options{retry},
    'dry_run|n'      => \$options{dry_run},
    'verbose|v+'     => \$options{verbose},
) || help();

help() if $options{help};

my $mode             = 'direct';
my $gearman_job_name = 'to_h264';

my $gearman;
if ( $options{client} ) {
    require Gearman::Client;
    $gearman = Gearman::Client->new;
    $gearman->job_servers( getGearmanServers( $options{gearman} ) );

    $mode = 'gearman_client';
    $options{client} = undef;

} elsif ( $options{worker} ) {
    require Gearman::Worker;
    $gearman = Gearman::Worker->new;
    $gearman->job_servers( getGearmanServers( $options{gearman} ) );
    $gearman->register_function( $gearman_job_name => \&process_file );

    $mode = 'gearman_worker';
    $options{worker} = undef;
}

$options{retry} ||= 0;

if ( scalar(@ARGV) == 0 and $mode ne 'gearman_worker' ) {
    while ( my $line = <STDIN> ) {
        chomp($line);
        push( @ARGV, $line );
    }
}

if ( $mode eq 'gearman_worker' ) {
    while (1) {
        eval { $gearman->work; } or do {
            warn "Strange??? $@";
        }

    }
}
for my $file (@ARGV) {
    if ( -d $file ) {

        # open directory and push files
        next;
    }

    # perhaps I should check at this point if the output is a directory or
    # file so that the worker can check and requeue the job if it can't see
    # either the input and the output

    my %client_args = %options;
    $client_args{file}      = abs_path($file);
    $client_args{output}    = abs_path( $client_args{output} || '.' );
    $client_args{retry_num} = 0;
    my $workload = encode_json( \%client_args );

    # warn Dumper(\%client_args); # EKT
    warn Dumper($workload) if $options{verbose};

    if ( $mode eq 'gearman_client' ) {
        my $result_ref = $gearman->dispatch_background( $gearman_job_name, $workload, () );
        print "Queued $file ($result_ref)\n";
    } else {
        eval { process_file($workload); } or do {
            warn $@ . "\n";
        }
    }
}

sub process_file {
    my $job = shift;

    my $workload;
    if ( ref($job) eq '' ) {
        $workload = $job;
    } elsif ( ref($job) eq 'Gearman::Job' ) {
        $workload = ${ $job->argref() };
    } else {
        print "REF??? " . ref($job) . "\n";
    }

    %options = %{ decode_json($workload) };

    if ( $options{verbose} and ref($job) eq 'Gearman::Job' ) {
        printf( "Job: %s\nWorkload: %s\n", $job->handle(), $workload );
    }

    warn Dumper( \%options ) if $options{verbose};

    my $file = $options{file};
    my $out  = $file;

    if ( defined( $options{output} ) ) {
        $out = $options{output};

        if ( -d $out ) {
            $out = $out . '/' . basename($file);
        }
    } else {
        $out = $file;
    }

    print "Encoding: $file\n";
    eval {
        # die("test\n");
        $out = set_extension( $out, 'm4v' );

        my $file_enc   = cmd_enc($file);
        my $out_enc    = cmd_enc($out);
        my $extra_args = '';

        if ( $options{preset} ) {
            $extra_args = " --preset='" . $options{preset} . "'";
        } elsif ( $options{high_quality} ) {
            $extra_args = " --preset='General/HQ 1080p30 Surround'";
        } else {
            $extra_args = " --preset='General/Fast 720p30'";
        }

        if ( $options{handbrake} ) {
            $extra_args .= ' ' . $options{handbrake};
        }

        my $m4v = $out;
        $m4v =~ s/m4v$/mp4/;
        if (
            !$options{force}
            && (
                -f $out
                ||

                # -f $mp4 ||
                # -f dirname($out).'/videos/'.basename($out) ||
                # -f dirname($out).'/videos/'.basename($m4v) ||
                0
            )
          )
        {
            die("$out already exists.  To overwrite use -f\n");
        }

        my $cmd = "HandBrakeCLI -i $file_enc -o $out_enc -O -r 29.97 -f mp4 " . "--main-feature " . $extra_args;

        if ( $options{nice} ) {
            $cmd = 'nice ' . $cmd;
        }
        my $exit_code = run($cmd);

        if ( $exit_code != 0 ) {
            die("Encode Failed with exit code: $exit_code\n");
        }

        if ( !-f $out ) {
            die("HandBrake failed to create the output file\n");
        }

        if ( $options{replace} && !$options{dry_run} ) {
            unlink($file);
        }
        1;
    } or do {
        my $message = $@;
        chomp($message);

        # print "job: $job\n";
        if ( ref($job) eq 'Gearman::Job' ) {
            require Gearman::Client;
            $gearman = Gearman::Client->new;
            $gearman->job_servers( getGearmanServers( $options{gearman} ) );
            $options{retry_num}++;
            my $retry_workload = encode_json( \%options );
            if ( $options{retry} > 0 and $options{retry_num} > $options{retry} ) {
                print "JOB FAILED only retried ($options{retry})\n$workload\n";
            } else {
                my $result_ref = $gearman->dispatch_background( $gearman_job_name, $retry_workload, () );
                print "Requeued[$options{retry_num}] Failed Job ($result_ref) :(\nMessage: $message\nWorkload: $workload\n\n";
                sleep 5;
            }
        } else {
            die( $message . "\n" );
        }

    }

}

sub cmd_enc {
    my $arg = shift;
    $arg =~ s/([^a-zA-Z0-9.\/_-])/\\$1/g;
    return $arg;
}

sub set_extension {
    my $file    = shift;
    my $new_ext = shift;

    my $out = $file;

    if ( $file =~ /\.(.{2,4})$/ ) {
        my $old_ext = $1;

        $out =~ s/$old_ext$/$new_ext/;
        if ( -f $out && $out eq $file ) {
            $out =~ s /\.$new_ext$/.new.$new_ext/;
        }
    } else {
        $out = $file . '.' . $new_ext;
        warn "Unable to determine file type for: $file\n" if ( $options{verbose} || 0 ) > 0;
    }

    return $out;
}

sub help {
    warn <<"END"
Usage: $0 [options] <files>
    --help, -h                This message
    --replace, -R             Replace original by deleting it on success
    --force, -f               Force output file even if it already exists
    --nice, -N                Nice the encoding process to reduce the system lag
    --output, -o <file>       Output file
    --high_quality, -H        Use high quality preset
    --preset, -p <preset>     Use <preset> preset
    --handbrake, -b <args>    Flags and options to pass directly to handbrake
    --gearman, -g <server(s)> Gearman server(s) (default: 127.0.0.1)
    --client, -c              Run as a gearman client (queue jobs)
    --worker, -w              Run as a gearman worker (accept jobs)
    --retry, -r <num>         Number of times to retry a job (default: 0 (unlimited))
    --dry_run, -n             Dry run.  Don't actually convert file(s)
    --verbose, -v             Verbose.  Show more output
END
      ;
    exit 1;
}

sub run {
    my $cmd = shift;
    if ( $options{verbose} or $options{dry_run} ) {
        print color("bold blue") . $cmd . color("reset") . "\n";
    }

    if ( !$options{dry_run} ) {

        # print "[[[$cmd]]]\n";
        system($cmd);
    }
    return $?;
}

sub getGearmanServers {
    my $arg = shift;

    if ( !$arg || length($arg) == 0 ) {
        $arg = '127.0.0.1';
    }

    my @servers = ($arg);
    if ( $arg =~ /,/ ) {
        @servers = split /,/, $arg;
    }
    for ( my $i = 0 ; $i < scalar(@servers) ; $i++ ) {
        if ( $servers[$i] !~ /:[0-9]+/ ) {
            $servers[$i] .= ':4730';
        }
        print "server $servers[$i]\n" if $options{verbose};
    }

    return @servers;
}
